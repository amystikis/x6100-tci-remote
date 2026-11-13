# Changelog

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
