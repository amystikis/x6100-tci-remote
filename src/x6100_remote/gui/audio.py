"""Audio in/out via Qt Multimedia. Everything degrades gracefully if it is unavailable."""
from __future__ import annotations

import threading

import numpy as np

try:
    from PySide6.QtCore import QObject
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices
    AVAILABLE = True
except Exception:                                          # pragma: no cover - depends on install
    AVAILABLE = False
    QObject = object                                       # type: ignore


def _fmt(rate: int, channels: int):
    f = QAudioFormat()
    f.setSampleRate(rate)
    f.setChannelCount(channels)
    f.setSampleFormat(QAudioFormat.SampleFormat.Float)
    return f


class RxAudio:
    """Plays the radio's RX audio (float32 interleaved stereo)."""

    def __init__(self) -> None:
        self._sink = None
        self._io = None
        self._rate = 0
        self.volume = 0.8
        self.muted = False

    def start(self, rate: int = 48000) -> bool:
        if not AVAILABLE:
            return False
        self.stop()
        try:
            dev = QMediaDevices.defaultAudioOutput()
            self._sink = QAudioSink(dev, _fmt(rate, 2))
            self._sink.setBufferSize(rate * 2 * 4 // 5)     # ~200 ms
            self._io = self._sink.start()
            self._rate = rate
            self._apply_volume()
            return self._io is not None
        except Exception:
            self._sink = self._io = None
            return False

    def stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()
        self._sink = self._io = None

    def push(self, data: bytes, rate: int) -> None:
        if self._io is None or self._sink is None:
            return
        if rate != self._rate:
            self.start(rate)
            if self._io is None:
                return
        free = self._sink.bytesFree()
        if free >= len(data):                  # drop rather than build up latency
            self._io.write(data)

    def set_volume(self, v: float) -> None:
        self.volume = v
        self._apply_volume()

    def set_muted(self, m: bool) -> None:
        self.muted = m
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._sink is not None:
            self._sink.setVolume(0.0 if self.muted else self.volume)


class MicSource:
    """Captures the default microphone as mono float32; ``read_frames`` returns stereo."""

    def __init__(self) -> None:
        self._src = None
        self._io = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    def start(self, rate: int = 48000) -> bool:
        if not AVAILABLE or self._src is not None:
            return self._src is not None
        try:
            self._src = QAudioSource(QMediaDevices.defaultAudioInput(), _fmt(rate, 1))
            self._io = self._src.start()
            self._io.readyRead.connect(self._on_ready)
            return True
        except Exception:
            self._src = self._io = None
            return False

    def stop(self) -> None:
        if self._src is not None:
            self._src.stop()
        self._src = self._io = None
        with self._lock:
            self._buf.clear()

    def _on_ready(self) -> None:
        data = bytes(self._io.readAll())
        with self._lock:
            self._buf += data
            del self._buf[:-48000 * 4]                       # keep at most ~1 s

    def read_frames(self, n: int) -> np.ndarray:             # called from the network thread
        need = n * 4
        with self._lock:
            chunk = bytes(self._buf[:need])
            del self._buf[:need]
        mono = np.frombuffer(chunk, dtype="<f4")
        if mono.size < n:
            mono = np.concatenate([mono, np.zeros(n - mono.size, dtype=np.float32)])
        return np.repeat(mono[:, None], 2, axis=1)
