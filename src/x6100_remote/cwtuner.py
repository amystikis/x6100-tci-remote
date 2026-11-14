"""CW tuning aid: where is the strongest signal relative to the VFO line, and how does it sit in the passband?

A CW station is tuned correctly when its peak sits one CW pitch from the VFO frequency (above it in CW, below it in
CW-R), the way other radios' CW tuning aids work. The pitch is the radio's ``kt`` (default 700 Hz). This module
reads the radio's spectrum bins around that point and estimates the peak's offset in Hz (parabolic
interpolation over the three bins at the peak).

The resolution is limited by the radio's spectrum frame: 1024 bins over the span (about 98 Hz per bin at 100 kHz).
Over a narrow window that is only a handful of bins, so the offset is an estimate, accurate to a few tens of Hz
at best; it improves when the span is smaller. The bin value scale is uncalibrated, so "strength" is in raw units.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .spectrum import SpectrumFrame

MIN_STRENGTH = 10.0           # peak above the median of the window, raw bin units, to count as a signal
ALIGNED_HZ = 20.0             # |offset| within this: "on the line"
SMOOTH_ALPHA = 0.1            # weight of each new frame in the offset average (lower: steadier, slower to follow)
HOLD_S = 2.0                  # keep showing the last reading this long after the signal drops (keyed CW has gaps)
SHOWN_EVERY_S = 0.3           # the readout is refreshed at most this often so the digits are readable
BAR_FALL_PER_S = 0.5          # peak-hold bars fall by this fraction of full scale per second


@dataclass
class CwTune:
    offset_hz: float          # peak frequency minus the VFO frequency (positive: peak is above the line)
    strength: float           # peak minus the median of the window (raw units)
    in_passband: bool         # peak falls inside the (centred) passband
    aligned: bool             # on the line, within ALIGNED_HZ


def window_levels(frame: SpectrumFrame, half_window_hz: float, n: int,
                  values: Optional[np.ndarray] = None, centre_hz: float = 0.0) -> np.ndarray:
    """``n`` values sampled evenly over centre +- ``half_window_hz`` (linear interpolation). Uses the raw bins unless
    ``values`` (one number per bin, e.g. auto-levelled 0..1) is given."""
    nb = len(frame.bins)
    centre_idx = nb / 2.0
    offsets = np.linspace(-half_window_hz, half_window_hz, n, endpoint=False) + half_window_hz / n
    idx = centre_idx + (centre_hz + offsets) / frame.hz_per_bin
    src = frame.bins if values is None else values
    return np.interp(idx, np.arange(nb), np.asarray(src, dtype=np.float64))


def target_hz(mode: str, pitch_hz: float) -> float:
    """Where a correctly tuned CW signal sits relative to the VFO frequency in the spectrum: the CW pitch above it in
    CW, below it in CW-R (the displayed frequency is the carrier; the signal is heard at the pitch)."""
    return -float(pitch_hz) if mode == "cwr" else float(pitch_hz)


def analyze(frame: SpectrumFrame, bandwidth_hz: float, half_window_hz: Optional[float] = None,
            target_hz: float = 0.0) -> Optional[CwTune]:
    """Find the strongest peak around ``target_hz`` (relative to the VFO). ``offset_hz`` is measured from the target,
    so 0 means on the CW pitch. Returns ``None`` when nothing stands out."""
    half = half_window_hz if half_window_hz is not None else window_half_width(bandwidth_hz)
    nb = len(frame.bins)
    if nb < 8 or frame.span_hz <= 0:
        return None
    hz_bin = frame.hz_per_bin
    vfo = nb / 2.0
    centre = vfo + target_hz / hz_bin
    lo = max(1, int(np.floor(centre - half / hz_bin)))
    hi = min(nb - 2, int(np.ceil(centre + half / hz_bin)))
    if hi < lo:
        return None
    seg = frame.bins[lo:hi + 1].astype(np.float64)
    k = int(np.argmax(seg))
    i = lo + k
    strength = float(seg[k] - np.median(seg))
    if strength < MIN_STRENGTH:
        return None
    y0, y1, y2 = (float(frame.bins[i - 1]), float(frame.bins[i]), float(frame.bins[i + 1]))
    denom = y0 - 2 * y1 + y2
    delta = 0.0 if denom == 0 else max(-0.5, min(0.5, 0.5 * (y0 - y2) / denom))
    offset = (i + delta - centre) * hz_bin
    return CwTune(offset, strength, abs(offset) <= bandwidth_hz / 2.0, abs(offset) <= ALIGNED_HZ)


def window_half_width(bandwidth_hz: float) -> float:
    """Half width (Hz) of the tuner window: a little wider than the passband, at least 300 Hz."""
    return max(bandwidth_hz * 0.8, 300.0)


def smooth(prev: Optional[CwTune], new: Optional[CwTune], bandwidth_hz: float, alpha: float = 0.25,
           jump_hz: float = 150.0) -> Optional[CwTune]:
    """Exponential smoothing of the offset over successive frames, so the display does not flicker.
    A new signal, or a jump of more than ``jump_hz`` (another station), restarts from the new value."""
    if new is None or prev is None or abs(new.offset_hz - prev.offset_hz) > jump_hz:
        return new
    off = prev.offset_hz + alpha * (new.offset_hz - prev.offset_hz)
    return CwTune(off, new.strength, abs(off) <= bandwidth_hz / 2.0, abs(off) <= ALIGNED_HZ)
