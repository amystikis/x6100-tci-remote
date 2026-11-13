"""TCI binary frames: a 64-byte little-endian header followed by samples.

Header (16 x uint32): receiver, sample_rate, format, codec, crc, length, type, reserved[9].
``length`` is the number of *samples* (floats for float32) that follow, counting every
channel. Audio is always stereo. Layout cross-checked against the JTDX and wfview sources
and the Expert Electronics developer forum."""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

HEADER_SIZE = 64
_HDR = struct.Struct("<7I9I")

STREAM_IQ, STREAM_RX_AUDIO, STREAM_TX_AUDIO, STREAM_TX_CHRONO = 0, 1, 2, 3
FORMAT_INT16, FORMAT_INT24, FORMAT_INT32, FORMAT_FLOAT32, FORMAT_FLOAT64 = 0, 1, 2, 3, 4


@dataclass
class StreamHeader:
    receiver: int
    sample_rate: int
    format: int
    codec: int
    crc: int
    length: int
    type: int

    def pack(self) -> bytes:
        return _HDR.pack(self.receiver, self.sample_rate, self.format, self.codec,
                         self.crc, self.length, self.type, *([0] * 9))

    @classmethod
    def unpack(cls, data: bytes) -> "StreamHeader":
        if len(data) < HEADER_SIZE:
            raise ValueError("TCI binary frame shorter than its 64-byte header")
        f = _HDR.unpack_from(data)
        return cls(*f[:7])


def decode_samples(fmt: int, payload: bytes, length: int) -> np.ndarray:
    """Decode ``length`` samples to float32 in -1..1 (flat array, channels interleaved)."""
    if fmt == FORMAT_FLOAT32:
        a = np.frombuffer(payload, dtype="<f4", count=length)
    elif fmt == FORMAT_FLOAT64:
        a = np.frombuffer(payload, dtype="<f8", count=length).astype(np.float32)
    elif fmt == FORMAT_INT16:
        a = np.frombuffer(payload, dtype="<i2", count=length).astype(np.float32) / 32768.0
    elif fmt == FORMAT_INT32:
        a = np.frombuffer(payload, dtype="<i4", count=length).astype(np.float32) / 2147483648.0
    elif fmt == FORMAT_INT24:
        raw = np.frombuffer(payload, dtype=np.uint8, count=length * 3).reshape(-1, 3)
        v = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
             | (raw[:, 2].astype(np.int32) << 16))
        v = np.where(v & 0x800000, v - 0x1000000, v)
        a = v.astype(np.float32) / 8388608.0
    else:
        raise ValueError("unsupported TCI sample format %d" % fmt)
    return a


def decode_stream(frame: bytes) -> tuple[StreamHeader, np.ndarray]:
    """Parse a binary frame -> (header, float32 samples, shape (n,) interleaved)."""
    hdr = StreamHeader.unpack(frame)
    return hdr, decode_samples(hdr.format, frame[HEADER_SIZE:], hdr.length)


def encode_tx_audio(samples: np.ndarray, sample_rate: int = 48000, receiver: int = 0) -> bytes:
    """Build a TX audio frame from float32 stereo samples (shape (n,2) or flat interleaved)."""
    flat = np.ascontiguousarray(samples, dtype="<f4").reshape(-1)
    hdr = StreamHeader(receiver, sample_rate, FORMAT_FLOAT32, 0, 0, flat.size, STREAM_TX_AUDIO)
    return hdr.pack() + flat.tobytes()
