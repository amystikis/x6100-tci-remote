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
