# Roadmap

Done: remote control over TCI, RX audio, guarded TX, spectrum + waterfall from the panel server (port 50002).

1. **Real-radio validation** of the spectrum widget, RX audio quality (the radio's README mentions int16 mono 24 kHz while
   it announces float32 stereo 48 kHz) and, into a dummy load, TX.
2. Compare the CW tuner offset with the radio's own tuner and a known signal; adjust the bin convention if needed.
3. Calibrate the spectrum level scale (compare bin values with the `m <dBm>` readings and a known signal) and add
   zoom/reference-level controls.
3. ~~Use the `spots`, `bands`, `plan`, `state`, `cw` data~~ (done). Still open: decoded FT8 messages, panel `state` updates, building the band buttons from the radio's own band list.
4. Digital modes would need the radio's audio only (no IQ): decode FT8 from the RX audio, or bridge TCI to other software.
5. Optional: browser/PWA front end, packaging as AppImage/Flatpak.

IQ over TCI is not available on this firmware (verified), so an own-demodulator SDR is not possible.

## Next phase (planned)

Make the app independent of the radio's own services by re-implementing their functions locally: a local rigctl server and
TCI sharing for loggers and digital-mode software, a local logbook (ADIF), a local DX spot source, decoders running on the
radio's RX audio.
