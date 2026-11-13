# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PySide6 desktop remote controller for the Xiegu X6100 radio (OpenX6X00 firmware). It talks to two
independent WebSocket servers on the radio: the standard **TCI** protocol (port 50001: tuning, mode,
filter, AGC, S-meter, RX/TX audio) and the radio's own **panel server** (port 50002: spectrum/waterfall,
band plan, DX spots, radio status, CW decoder text, pairing and the five whitelisted hardware key presses).
There is no vendor spec for the panel server — its format was reverse-engineered from the radio's web UI and
is documented, with the TCI details, in `docs/PROTOCOL.md`.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui,dev]"            # GUI (PySide6) + dev (pytest, ruff)

QT_QPA_PLATFORM=offscreen pytest -q    # full test suite (GUI tests need an offscreen Qt platform)
pytest -q tests/test_protocol.py       # single file
pytest -q tests/test_protocol.py::test_name   # single test
ruff check .                           # lint (line-length 120, py310 target)

x6100-tci-remote --demo                # run the app against the built-in fake radio, no hardware
x6100-tci-remote 192.168.0.150          # run against a real radio
python -m x6100_remote.fakeradio --port 50001          # fake radio standalone (pairing code 123456)
python scripts/probe_tci.py 192.168.0.150               # passive protocol probe, sends nothing
```

CI (`.github/workflows/ci.yml`) splits into a `core` job (ruff + `test_protocol.py` + `test_client_fake.py`,
no Qt) and a `gui` job (full `pytest -q` under `QT_QPA_PLATFORM=offscreen`, needs system Qt libs). Keep
protocol/client logic testable without Qt so it stays in the `core` job.

VS Code: open the folder, run task **Set up venv (dev + GUI)**, then use the launch configs (demo app, fake
radio, probe) and the Testing panel; see `.vscode/launch.json` / `tasks.json`.

## Architecture

### Two independent connections, one per radio service

`gui/worker.py`'s `TciWorker` (a `QObject`) runs its own asyncio event loop on a background thread and owns
*two* separate reconnect-with-backoff sessions, bridged to Qt signals for the GUI thread:

- a `tci.client.TciClient` session against port 50001 (tuning/mode/audio/S-meter)
- a `spectrum.PanelClient` session against port 50002 (spectrum frames, pairing, key presses, band/spot/status
  text)

Both reconnect independently (exponential backoff, capped at 10s) and both are torn down on disconnect/shutdown
by sending a "stop transmitting" command first — the radio must never be left keyed. `worker.submit(coro)` is
the only way GUI code should schedule work on the asyncio loop; nothing in `gui/` talks to a socket directly.

### TCI stack (`src/x6100_remote/tci/`)

Layered so each piece is independently testable:
- `protocol.py` — wire format only: `name:arg,arg;` text commands, parsing/formatting, S-meter dBm→S-unit math.
- `state.py` — `RadioState`, a dataclass updated by `RadioState.apply(Command)`; returns the changed field name
  (used to decide which Qt signal to emit) or `None` for unrecognised commands.
- `stream.py` — the 64-byte binary frame header and sample decode/encode (int16/24/32, float32/64 → float32).
- `client.py` — `TciClient.run()` owns the websocket; dispatches text frames into `state.apply` and binary
  frames by type (RX audio → `on_audio`, TX_CHRONO → calls `tx_source` and replies with TX_AUDIO, everything
  else → `on_stream`). All three callbacks (`on_command`, `on_audio`, `on_stream`) run on the event-loop thread.

### Panel server stack

- `spectrum.py` — `PanelClient` (the websocket session, spectrum frame parsing) plus `is_allowed()`, an
  explicit allowlist of every string this app will ever send to the panel socket (3 subscription commands,
  pairing, `control take/release`, and `key <NAME> 0|1` for exactly `PRE/AB/VM/FST/ATU`). Any new outbound
  panel command must be added here deliberately — this is a safety boundary, not incidental validation; the
  app must never be able to send POWER or PTT over this channel.
- `panelinfo.py` — `PanelInfo`, decodes the panel server's descriptive text lines (`bands`, `plan`, `spots`,
  `state`, `ft8`, `cw`, `role`, `ctl`) into structured data. `merge_cw()` exists because it's unknown whether
  the radio's CW decoder sends incremental text or its whole buffer each time — it handles both without
  duplicating.

### GUI layer (`src/x6100_remote/gui/`)

`main_window.py` (`MainWindow`) builds the Qt widgets and wires their signals to `TciWorker` methods and
`RadioState`/`PanelInfo` fields; `spectrum_view.py` draws the spectrum/waterfall, band-plan strip and DX
spots; `audio.py` handles RX playback and mic capture for TX; `widgets.py` has the frequency display and
S-meter; `settings.py` persists window state, paired-radio keys and band memory (QSettings).

### Fake radio (`fakeradio.py`)

`FakeRadio` + `FakePanel` reimplement both servers' observed behaviour (state echo, S-meter, RX/TX audio,
spectrum frames with synthetic carriers, pairing with a fixed code `123456`, spots/band-plan/CW text) and
back both `x6100-tci-remote --demo` and the test suite — there's no real radio in CI. Treat it as the
executable spec for "what does the radio send back after command X."

### Cross-cutting conventions

- **Transmit safety is structural, not just UI state.** PTT guards (enable-transmit checkbox, auto-unkey
  timer, unkey on focus loss, disconnect always sends `trx:0,false` first) live in `main_window.py` and
  `worker.py` together — if you touch one you likely need the other. The panel key allowlist in `spectrum.py`
  is the second half of this: it is what stops a bug from ever being able to press POWER or PTT.
- **CW tuning math** (`cwtuner.py`) measures against the radio's own CW pitch (`kt` in panel `state`, default
  700 Hz), not a fixed offset — a correct-looking hardcoded pitch is a regression.
- `ipc.py` is a tiny local (Unix-socket) command channel so `x6100-tci-remote --ptt toggle` can drive an
  already-running instance from an OS keyboard shortcut; it is intentionally not reachable over the network
  and only understands the fixed `COMMANDS` tuple.
