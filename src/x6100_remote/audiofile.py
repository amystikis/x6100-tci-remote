"""WAV files for the recorder and for playback-transmit (no Qt, so it is testable on its own).

* :class:`WavRecorder` writes the radio's RX audio (float32 interleaved stereo) to a 16-bit PCM WAV file as it arrives.
* :func:`read_audio` reads PCM (8/16/24/32 bit) and IEEE-float WAV files, including the "extensible" header.
* :class:`FilePlayer` turns such a file into the 48 kHz stereo float32 blocks the radio asks for while it transmits
  (``TciClient.tx_source``); it appends a short silent tail so the end of the file is not cut off by unkeying.
"""
from __future__ import annotations

import struct
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

TX_RATE = 48000
TAIL_S = 0.4                    # silence after the file, before the player reports it is done
MAX_REC_S = 3600                # a recording stops by itself after an hour


def default_rec_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "x6100-recordings"


def recording_name(freq_hz: int, mode: str, now: Optional[datetime] = None) -> str:
    """``x6100_20261126_114530Z_7151.000kHz_LSB.wav``: UTC time, frequency and mode, handy for later analysis."""
    t = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%SZ")
    return "x6100_%s_%.3fkHz_%s.wav" % (t, freq_hz / 1000.0, (mode or "unknown").upper())


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    n = 2
    while p.exists():
        p = folder / ("%s_%d%s" % (Path(name).stem, n, Path(name).suffix))
        n += 1
    return p


class WavRecorder:
    """Streams float32 interleaved audio into a 16-bit PCM WAV file."""

    def __init__(self, path: Path, rate: int, channels: int = 2) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.rate, self.channels = path, rate, channels
        self.frames = 0
        self._wf = wave.open(str(path), "wb")
        self._wf.setnchannels(channels)
        self._wf.setsampwidth(2)
        self._wf.setframerate(rate)

    @property
    def seconds(self) -> float:
        return self.frames / self.rate

    def write(self, data: bytes) -> None:
        a = np.frombuffer(data, dtype="<f4")
        a = a[: a.size - a.size % self.channels]
        pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2")
        self._wf.writeframes(pcm.tobytes())
        self.frames += a.size // self.channels

    def close(self) -> None:
        if self._wf is not None:
            self._wf.close()
            self._wf = None


def read_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a WAV file -> (float32 samples shaped (frames, channels) in -1..1, sample rate)."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack_from("<I", raw, pos + 4)[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    if fmt is None or data is None or len(fmt) < 16:
        raise ValueError("WAV file has no audio data")
    tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", fmt)
    if tag == 0xFFFE and len(fmt) >= 26:                       # WAVE_FORMAT_EXTENSIBLE: real tag in the sub-format
        tag = struct.unpack_from("<H", fmt, 24)[0]
    if channels < 1 or rate < 1000:
        raise ValueError("unsupported WAV header")
    if tag == 1 and bits == 8:
        a = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif tag == 1 and bits == 16:
        a = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(data[: len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        a = np.where(v & 0x800000, v - 0x1000000, v).astype(np.float32) / 8388608.0
    elif tag == 1 and bits == 32:
        a = np.frombuffer(data[: len(data) // 4 * 4], dtype="<i4").astype(np.float32) / 2147483648.0
    elif tag == 3 and bits == 32:
        a = np.frombuffer(data[: len(data) // 4 * 4], dtype="<f4").astype(np.float32)
    elif tag == 3 and bits == 64:
        a = np.frombuffer(data[: len(data) // 8 * 8], dtype="<f8").astype(np.float32)
    else:
        raise ValueError("unsupported WAV format (tag %d, %d bit); use 16-bit PCM" % (tag, bits))
    a = a[: a.size - a.size % channels].reshape(-1, channels)
    if a.shape[0] == 0:
        raise ValueError("WAV file is empty")
    return np.nan_to_num(a), rate


def to_tx_stereo(samples: np.ndarray, rate: int, target: int = TX_RATE) -> np.ndarray:
    """Mix to mono, resample to ``target`` Hz and return stereo (frames, 2) float32. Linear interpolation after a
    box low-pass when reducing the rate: plenty for speech, not meant for hi-fi."""
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    mono = mono.astype(np.float32)
    if rate != target:
        if rate > target:
            k = int(round(rate / target))
            if k > 1:
                mono = np.convolve(mono, np.ones(k, dtype=np.float32) / k, mode="same")
        n = max(1, int(round(mono.size * target / rate)))
        mono = np.interp(np.arange(n) * (rate / target), np.arange(mono.size), mono).astype(np.float32)
    return np.repeat(mono[:, None], 2, axis=1)


class FilePlayer:
    """Hands out TX audio blocks from a file; ``gain`` (0..1) can change while it plays."""

    def __init__(self, samples: np.ndarray, rate: int, gain: float = 0.6, target: int = TX_RATE) -> None:
        self.data = to_tx_stereo(samples, rate, target)
        self.tail = int(TAIL_S * target)
        self.rate = target
        self.gain = gain
        self._pos = 0
        self._lock = threading.Lock()

    @property
    def total(self) -> int:
        return self.data.shape[0]

    @property
    def seconds(self) -> float:
        return self.total / self.rate

    @property
    def position_s(self) -> float:
        return min(self._pos, self.total) / self.rate

    @property
    def done(self) -> bool:
        return self._pos >= self.total + self.tail

    def read_frames(self, n: int) -> np.ndarray:             # called from the network thread
        with self._lock:
            out = np.zeros((n, 2), dtype=np.float32)
            start, avail = self._pos, max(0, self.total - self._pos)
            take = min(n, avail)
            if take:
                out[:take] = self.data[start:start + take]
            self._pos += n
        return np.clip(out * float(self.gain), -1.0, 1.0)
