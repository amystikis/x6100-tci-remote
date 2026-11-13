# x6100-tci-remote

A native desktop remote controller for the **Xiegu X6100** running the **OpenX6X00** firmware. It talks to the
radio's built-in **TCI** WebSocket server (default port 50001): tune, change mode/filter/AGC, listen to receiver
audio, read the S-meter, and (optionally, behind guards) transmit.

![screenshot](docs/screenshot.png)

## Status (be honest about it)

- Verified against a **fake radio** included in this repo, and against the real radio's announced init burst (passive probe).
- **Not yet run against a real radio** end to end. Audio has not been tested on real hardware.
- **Transmit is experimental.** Test only into a dummy load.
- Whether the radio streams **IQ** over TCI is unknown. Use `scripts/probe_tci.py` to find out (see Roadmap).

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui]"          # or: pipx install ".[gui]"
```

Optional `.deb` (needs PySide6 packages available from your distro): `packaging/build_deb.sh`.

## Run

```bash
x6100-tci-remote 192.168.0.150     # your radio's address (port defaults to 50001)
x6100-tci-remote --demo            # no hardware: starts the built-in fake radio
```

In the radio's web UI (`/tci`) enable TCI. **Listen-only** is enough for monitoring; use **Operate** to control it.

## Safety

- Transmit controls are off until you tick "Enable transmit controls".
- PTT is hold-to-talk, auto-unkeys after a timeout (default 120 s), and unkeys on focus loss, disable and close.

## Development (VS Code)

Open the folder in VS Code and accept the recommended extensions. Run the task **Set up venv**, then use the
launch configs (demo app, fake radio, probe) and the Testing panel. From a shell:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
ruff check .
```

## Docs

- [docs/PROTOCOL.md](docs/PROTOCOL.md) - what the radio exposes and how the app talks to it
- [docs/ROADMAP.md](docs/ROADMAP.md) - next steps

## License

MIT
