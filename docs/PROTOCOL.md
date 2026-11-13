# Protocol notes

## Radio ports (OpenX6X00, radio at e.g. 192.168.0.150)

| Port | Use |
|------|-----|
| 80 / 443 | Web UI: `/remote` (screen mirror), `/panel` (spectrum), `/tci` (TCI config) |
| 50001 | TCI WebSocket server (this app) |
| 50002 | Screen-mirror WebSocket (JPEG frames, 800x480) |

`/api/remote` returns `{enabled, port, tci_enabled, tci_port}`. TCI has an *Operate* and a *Listen-only* mode; no login.

## TCI

Text frames carry one or more commands: `name:arg,arg;`. The radio announces `device:OpenX6X00`, protocol
`ExpertSDR3`, `if_limits:-48000,48000`, the modulation list and its state on connect.

Used commands: `vfo`, `modulation`, `rx_filter_band`, `agc_mode`, `rit_enable`, `split_enable`, `lock`,
`drive`, `trx:<rx>,<bool>[,tci]`, `audio_start`, `audio_stop`, `rx_smeter` / `rx_sensors`.

## Binary stream frames

Little-endian, 64-byte header (`<7I9I`): receiver, sample rate, format, codec, crc, length, type, channels,
reserved. Types: 0 IQ, 1 RX audio, 2 TX audio, 3 TX chrono. Observed audio: 48 kHz float32 stereo, 2048 samples
per frame. For TX the radio sends TX_CHRONO frames; the client answers with TX_AUDIO of the same sample count.

S9 = -73 dBm, 6 dB per S-unit.

## Panel server (port 50002): spectrum

Same server as the screen mirror. On connect it sends text lines (`hello OpenX6X00 - v0.3.9 ...`, `size 800 480`,
`keys ...`, `role view 0 -`, `ctl none 0`, then JSON lines such as `spots`, `bands`, `state`, `ft8`) and `m <dBm>` S-meter
lines. The web page sends `auth <token>`, `screen 1`, `panel 1`, `ping 1`. This app sends only `screen 0`, `panel 1`, `ping 1`
and no token (the `view` role needs none).

Spectrum frame, binary, little endian, 16 + 1024 bytes, about 14 per second:

    u16 0xFFFF | u16 nbins (1024) | u32 centre Hz (= VFO) | u32 span Hz (100000 observed) | u32 counter | nbins x u8

Bin values are an uncalibrated level scale (typically 128-175 on a quiet band); the viewer auto-scales. The screen frames
(`screen 1`) are an 8-byte header (`u16 800, u16 480, u32 counter`) followed by a JPEG.

IQ is **not** offered over TCI: `iq_start` at 96 kHz produced no binary frames.

### Descriptive text messages on the panel server

Decoded by `src/x6100_remote/panelinfo.py` (formats and examples are in its docstring): `bands`, `plan`
(`[lo, hi, kind]`, kind 0 CW / 1 digital / 2 phone / 3 other, inferred), `spots` (resent about every 15 s; `a` looks like age in
minutes), `state` (sent on connect; later updates not yet observed), `ft8` and `cw` (decoded text; whether it sends increments or
the whole buffer is not known, so the client merges both ways).

### Control over the panel socket (pairing and keys)

Taken from the radio's web page code; the exact replies are partly inferred and **not yet confirmed on a real radio**.

- A new device first sends `pair?`, which makes the radio show a 6-digit code on its own screen for two minutes. It then
  sends `pair <6-digit code> <name>`; the radio answers `paired <role> ...` (role `operate` or `admin`) and a
  key, which the device stores and sends first on later connections as `auth <key>`. Unpaired connections get `role view 0 -`.
- `control take` / `control release` claim and release control. Key presses are `key NAME 1` then `key NAME 0`.
- Keys the radio lists: POWER GEN KEY DFN PTT BAND_DOWN BAND_UP APP MSG DFL AM CW SSB F1-F5 AB PRE ATU VM AGC FST LOCK VOL MFK.
  This app whitelists PRE, AB, VM, FST, ATU only. NB, NR, attenuator, squelch and RF gain have no key.
- Other commands the page knows but this app does not use: `tune`, `vol`, `ft8`, `logq`, `sessions`, `revoke`, `unpair`, `away`.
