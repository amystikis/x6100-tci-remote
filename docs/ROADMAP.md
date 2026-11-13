# Roadmap

1. **Real-radio validation** of control, RX audio and (into a dummy load) TX.
2. **IQ test**: `python scripts/probe_tci.py <addr> --iq-test --yes-send-commands` (sends `iq_samplerate`/`iq_start`
   then `iq_stop`). If IQ arrives, the independent SDR phase is possible.
3. **Panel spectrum capture**: work out the data format behind the radio's `/panel` page (about 14 kB/s).
4. If IQ is available: own waterfall/panadapter, demodulators (SSB/CW/AM/FM), then digital modes (e.g. FT8).
5. TCI bridge for third-party logging/digital software; optional browser/PWA front end.
