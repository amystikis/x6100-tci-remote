# Changelog

## Unreleased

- Windows: an `.msi` installer (Program Files, Start menu and desktop shortcuts, in-place upgrades) built next to the zip, and an application icon for the exe.

## 0.3.1

- Descriptions (About, README, `.deb`, app menu entry) now say the Xiegu X6100 and X6200.
- CW tuner indicator is steadier: heavier averaging, the readout refreshes about 3 times a second, the last reading is held for 2 s when the signal pauses, and the bars are peak-held and fall slowly.
- README updated with the new features and a new screenshot taken from a live radio.

## 0.3.0

- `.deb`: real maintainer (Apostolis Mystikis, M7SVA), homepage and a fuller description.
- Windows: install instructions, a PyInstaller build script (`packaging/build_windows.ps1`) and a Windows CI job that runs the tests and builds the zip.
- Spectrum and waterfall zoom (1x, 2x, 4x, 8x) next to the frequency step. It is a display zoom of the middle of the radio's 100 kHz span (the panel protocol has no span command), so the resolution does not improve; the choice is remembered.
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
