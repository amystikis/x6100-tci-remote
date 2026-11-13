# Roadmap

Done (0.2.0, tested on a real X6100): remote control over TCI, RX audio, guarded TX, spectrum + waterfall from the panel
server (port 50002), band plan, DX spots, status strip, CW decoder text, CW tuner indicator (pitch based), radio key buttons
with pairing, View toggles, OS-hotkey PTT, `.deb` packaging.

Open:

1. Into a dummy load: TX. RX audio format (the radio's README mentions int16 mono 24 kHz, it announces float32 stereo 48 kHz).
2. Calibrate the spectrum level scale (compare bin values with the `m <dBm>` readings and a known signal) and add
   zoom/reference-level controls.
3. Decoded FT8 messages from the panel, building the band buttons from the radio's own band list.
4. Digital modes need the radio's audio only (no IQ): decode FT8 from the RX audio, or bridge TCI to other software.
5. Optional: AppImage/Flatpak.

IQ over TCI is not available on this firmware (verified), so an own-demodulator SDR is not possible.

## Next phase (planned)

Make the app independent of the radio's own services by re-implementing their functions locally: a local rigctl server and
TCI sharing for loggers and digital-mode software, a local logbook (ADIF), a local DX spot source, decoders running on the
radio's RX audio.
