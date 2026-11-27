# Changelog

## 0.3.6

- Audio recorder: **Rec** saves the radio's receive audio to a WAV file (48 kHz, 16 bit, stereo) named with the UTC time, frequency and mode; works with Sound off; stops after an hour, on disconnect or on a disk error. The folder is set in Settings > Operating.
- Playback-transmit: **File... / Transmit file** sends a WAV file (PCM or float, any rate) over the air with a level slider, a confirmation, the transmit-enable and auto-unkey guards, a Stop button, and unkeys itself when the file ends.
- New module `audiofile.py` (WAV reading/writing, resampling, file player) with its own Qt-free tests.
- The "TX - the radio sends no spectrum while transmitting" label on the dimmed spectrum was drawn in a 1-point font and could not be read; it now has a fixed size and sits at the top left, clear of the TX meter popup.
- README: new Transmit section and a screenshot of the TX meter popup.
- `.deb` installs can now be kept current with `apt`: a signed apt repository is published on the `gh-pages` branch and rebuilt on every release, instead of only attaching the `.deb` to the GitHub release. See the README's "Updating with apt" section.

## 0.3.5

- Transmit meter popup: while transmitting, power, SWR and ALC are shown in a popup over the bottom right of the spectrum, with a running transmit timer. The values come from the radio's `t` lines on the panel connection. SWR is light green up to 2.0, amber up to 2.5 and red above.
- The radio sends no spectrum while it transmits: the spectrum and waterfall are now dimmed and labelled, and the waterfall keeps scrolling with empty rows.
- The PTT section shows **Power** in watts (0.1 - 10 W) instead of the raw drive value, matching the radio's own display.
- Hold-to-transmit key: Space (or a key you choose) keys the radio wherever the focus is in the active window, except in text and number fields. Settings > Keyboard turns it on or off and picks the key. A key-repeat release no longer drops the transmission, and the status bar says why a transmission ended (focus lost, the radio ended it, time limit).
- The PTT button now releases when the radio is unkeyed by the key, the timer or a focus loss (it used to stay red).
- Automatic mode: tuning into another band or segment sets LSB on 160/80/60/40 m, USB from 30 m up, DIGU in the band plan's digital segments and CW in its CW segments. Settings > Operating turns it off. 60 m now defaults to LSB.
- The fake radio sends TX meter lines and no spectrum while transmitting, like the real radio.

## 0.3.4

- `.deb`: the Qt/xcb system libraries (including `libxcb-cursor0`) are now hard dependencies instead of recommendations, so the app no longer fails to start with "Could not load the Qt platform plugin xcb" on a fresh install.
- Themes: Settings > Theme with Midnight (the original look), Dark, Light and Night red (red tones only, to keep night vision). The spectrum and waterfall keep their dark scope in every theme. The choice is remembered.
- View > Transmit / PTT shows or hides the whole transmit box.
- Full screen without window borders: button next to Zoom, View > Full screen, F11; Esc leaves it.
- The UTC clock is bigger and sits in its own box to the right of the frequency.
- Spectrum: a Red trace colour, and an auto noise floor for the trace (with a trim slider) like the waterfall one, in Settings > Display.
- DX call-sign colour choice in Settings > Display (by mode, or one colour for all).
- In AM, DSB and FM the passband is drawn on both sides of the frequency marker.
- CW decoder: the Clear button now stays cleared (the old text used to come back with the next message); the field is 3 lines tall.
- Settings > Connection also shows the pairing state with a Pair button, and the Connect button turns into Disconnect while connected.
- The device line under the frequency shows only the radio name (the TCI protocol name is in its tooltip).
- Help > About: states that the app is not affiliated with OpenX6X00, credits all its authors and contributors, and points to the GitHub page for bugs and reports.
- The Windows installer and zip are confirmed working on a real PC.

## 0.3.3

- Waterfall noise floor: Settings > Display has an auto noise floor (on by default; the waterfall follows the noise floor and only signals light up), a noise-floor trim slider, a contrast slider and a reset button. They are remembered.

## 0.3.2

- The app connects automatically at start-up to the radio used last time (when its saved address is valid); a radio address given on the command line still wins. The zoom always starts at 1x.
- Windows: an `.msi` installer (Program Files, Start menu and desktop shortcuts, in-place upgrades) built next to the zip, and an application icon for the exe.

## 0.3.1

- Descriptions (About, README, `.deb`, app menu entry) now say the Xiegu X6100 and X6200.
- CW tuner indicator is steadier: heavier averaging, the readout refreshes about 3 times a second, the last reading is held for 2 s when the signal pauses, and the bars are peak-held and fall slowly.
- README updated with the new features and a new screenshot taken from a live radio.

## 0.3.0

- `.deb`: real maintainer (Apostolis Mystikis, M7SVA), homepage and a fuller description.
- Windows: install instructions, a PyInstaller build script (`packaging/build_windows.ps1`) and a Windows CI job that runs the tests and builds the zip.
- Spectrum and waterfall zoom (1x, 2x, 4x, 8x) next to the frequency step. It is a display zoom of the middle of the radio's 100 kHz span (the panel protocol has no span command), so the resolution does not improve.
- New Settings dialog (Settings > Settings...) with a Display tab: 6 waterfall colour schemes and 5 spectrum trace colours, applied immediately and remembered.
- The radio address and Connect button moved to Settings > Connection; the connection status is now shown at the bottom of the window. A UTC clock (amber, like the frequency) sits at the top right.
- Help > About is now a dialog: it states that the app works only with the OpenX6X00 firmware (https://openx6x00.org/) and credits RF.Guru (Joeri Van Dooren ON6URE) and everyone contributing to that open-source firmware.
- Relicensed from MIT to LGPL-2.1-or-later.

## 0.2.3

- The window now fits on 1920x1080 screens: tighter group-box padding, a smaller spectrum-view minimum, and an
  initial size computed from the screen's available area instead of a hardcoded 760x1040. Window size and
  position are now remembered across restarts.
- Frequency display: click a digit to select it (shown with an underline), then Left/Right move the selection
  and Up/Down change that digit, same as clicking its upper/lower half.

## 0.2.2

- `.deb`: fix the app not starting after install. The code now lives in `/usr/lib/x6100-tci-remote` and the launcher puts it on
  `PYTHONPATH`, so the private virtualenv (which holds PySide6, websockets, numpy) can import it.

## 0.2.1

- `.deb`: only `python3` and `python3-venv` are hard dependencies now (the Qt system libraries are recommended), so apt cannot refuse
  the install over a library name that differs on your distro. The file name carries the new version.

## 0.2.0

Tested by the author against a real X6100 (OpenX6X00 firmware): spectrum, pairing, radio keys, CW decoder text and CW tuner.

- Spectrum and waterfall from the radio's panel server (click to tune, wheel to step, passband overlay, hover read-out).
- Band plan strip, DX spots on the scope, status strip, CW decoder text (shown only in CW/CW-R).
- Radio key buttons PRE, A/B, V/M, FST, ATU and Tune ATU in the Receiver box, with pairing (`pair?`, then the code shown on the radio).
- View menu toggles for the Band, Mode, Receiver and Audio boxes, spectrum, CW tuner and DX spots.
- PTT from an OS keyboard shortcut: `x6100-tci-remote --ptt on|off|toggle`.
- Drive slider sends live (throttled) on drag, wheel, keys and click.
- CW tuner indicator: measures against the CW pitch (the radio's `kt`; VFO + pitch in CW, VFO - pitch in CW-R), meter at the
  top-left of the VFO line, DX spot labels keep clear of it.
- Packaging: the `.deb` installs PySide6, websockets and numpy from PyPI into `/opt/x6100-tci-remote/venv` on install (needs internet once; Debian/Ubuntu do not package PySide6 under a stable name), depends on the Qt/xcb system libraries, and ships docs and a copyright file.

## 0.1.0

First version: remote control over TCI (tune, mode, filter, AGC, RIT, split), RX audio, guarded TX, S-meter, fake radio for
development and tests.
