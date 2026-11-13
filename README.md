# x6100-tci-remote

A native desktop remote controller for the **Xiegu X6100** running the **OpenX6X00** firmware. It talks to the
radio's built-in **TCI** WebSocket server (default port 50001): tune, change mode/filter/AGC, listen to receiver
audio, read the S-meter, see a **spectrum and waterfall** (click to tune), and (optionally, behind guards) transmit.

![screenshot](docs/screenshot.png)

## Status

- **Version 0.2.2.** The author has tested it against a real X6100 (OpenX6X00 firmware): tuning and mode, spectrum and
  waterfall, pairing, the radio key buttons, the CW decoder text and the CW tuner indicator all work.
- Automated tests run against a **fake radio** included in this repo (`x6100-tci-remote --demo`).
- **Transmit is experimental.** Test only into a dummy load.
- The radio does **not** stream IQ over TCI (tested with `scripts/probe_tci.py`), so there are no own demodulators. The
  spectrum comes from the radio's panel server (port 50002) instead.
- Reply formats of the pairing exchange were partly inferred from the radio's web page; see `docs/PROTOCOL.md`.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui]"          # or: pipx install ".[gui]"
```

On Debian/Ubuntu, Qt may need `sudo apt install libxcb-cursor0` (error "could not load the Qt platform plugin xcb").

### Debian package

Build and install a `.deb` (Debian, Ubuntu, Mint, Raspberry Pi OS):

```bash
packaging/build_deb.sh                         # writes build/x6100-tci-remote_<version>_all.deb
sudo apt install ./build/x6100-tci-remote_*_all.deb
```

Releases on GitHub carry the built `.deb`. If an install is refused, `sudo apt install -f` and the exact apt message tell you which library is missing. apt installs python3-venv and (as recommends) the Qt/xcb system libraries; the package's post-install step then
creates `/opt/x6100-tci-remote/venv` and installs PySide6, websockets and numpy from PyPI into it (internet needed once;
Debian/Ubuntu do not ship PySide6 under a stable package name, and their `websockets` is older than the version needed).
If that step could not reach the internet, run the `pip install` line it prints. Removing the package deletes the venv.
Start the app from the application menu or run `x6100-tci-remote`.

## Run

```bash
x6100-tci-remote 192.168.0.150     # your radio's address (port defaults to 50001)
x6100-tci-remote --demo            # no hardware: starts the built-in fake radio
```

In the radio's web UI (`/tci`) enable TCI. **Listen-only** is enough for monitoring; use **Operate** to control it.

## Spectrum and waterfall

The app also connects to the radio's panel server (port 50002, the same server as the web page `/panel`) and sends only
`screen 0`, `panel 1` and `ping 1`: it turns the screen images off and the spectrum on. It never sends key presses.
Click the spectrum to tune, scroll the wheel to step. The orange band is the receive passband. Level scaling is
automatic (the radio's bin values are not calibrated). Hide it with View > Spectrum & waterfall.

### Extras from the panel server

- **Band plan** as a coloured strip under the frequency axis (blue CW, purple digital, green phone, grey other).
- **DX spots** (the radio's cluster feed) as call-sign labels on the spectrum: click one to tune to its exact
  frequency, hover for comment and spotter. Toggle in View > DX spots on spectrum.
- **Radio status strip**: preamp, attenuator, NB, NR, squelch, RF gain, power, tuner, battery, FT8 app open (read-only).
- **CW decoder** text decoded by the radio, shown when you are in CW or text arrives.

### Radio keys (Receiver box)

PRE, A/B, V/M, FST and ATU act like pressing those keys on the radio (sent over the panel socket; TCI cannot do
them). PRE and ATU light up from the radio's reported state. **They need this app to be paired with the radio**:
click **Pair...**: the app asks the radio for a code (it appears on the radio's screen for two minutes; later via Settings > General > BROWSER REMOTE > Pair code), you type it in, and the key the radio returns is saved for that radio.
Until paired, the buttons only tell you so and send nothing. The app can only ever press those five keys (never
POWER or PTT). **Tune ATU** makes the radio transmit a carrier while it tunes, so it also needs "Enable transmit
controls". With `--demo`, the fake radio's pairing code is `123456`.

## CW tuner indicator

Like other radios' CW tuning aids (Yaesu, Elecraft, UHSDR), the tuner measures against the **CW pitch**: a CW signal is
on tone when its peak sits one pitch above the VFO frequency (below it in CW-R), because the displayed frequency is the
carrier and the signal is heard at the pitch. The pitch is the radio's own setting (`kt` in the panel state, default
700 Hz). In CW and CW-R the receive passband is drawn there, and a row of vertical bars (the spectrum around that point)
sits at the top-left of the VFO line, with the strongest signal highlighted (green when on tone, orange inside the
passband, red outside) and its offset from the tone in Hz beside the meter. Tune until the offset is near 0. The offset
is an estimate from the radio's spectrum bins (about 98 Hz per bin at the 100 kHz span), smoothed over frames: expect an
accuracy of a few tens of Hz. Switch it off in View > CW tuner indicator.

## PTT from an OS keyboard shortcut

While the app is running, this command keys or unkeys the radio, so any desktop keyboard shortcut can do it:

```bash
x6100-tci-remote --ptt toggle     # or: on | off
```

In GNOME (Settings > Keyboard > Custom Shortcuts) or KDE (Shortcuts > Custom Shortcuts) use the full path of the
command, e.g. `/home/you/x6100-tci-remote/.venv/bin/x6100-tci-remote --ptt toggle`. Desktop shortcuts fire on key *press*
only, so this is a toggle, not hold-to-talk (on X11, `xbindkeys` can run `--ptt on` on press and `--ptt off` on release).
It has the same guards as the PTT button: "Enable transmit controls" must be ticked and the radio connected, and the
auto-unkey timer still applies; a hotkey-keyed PTT does not drop when the window loses focus. `--ptt off` always works.
The command talks to the running app over a per-user local socket, never over the network.

## View menu

Band, Mode, Receiver and Audio can each be hidden or shown from View; the choice is remembered.

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
