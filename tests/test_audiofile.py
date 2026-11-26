import struct
import wave
from datetime import datetime, timezone

import numpy as np
import pytest

from x6100_remote.audiofile import (FilePlayer, WavRecorder, read_audio, recording_name, to_tx_stereo, unique_path)


def _tone(rate=48000, secs=1.0, hz=1000.0):
    t = np.arange(int(rate * secs)) / rate
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_recording_name_has_utc_time_frequency_and_mode():
    n = recording_name(7_151_000, "lsb", datetime(2026, 11, 26, 11, 45, 30, tzinfo=timezone.utc))
    assert n == "x6100_20261126_114530Z_7151.000kHz_LSB.wav"


def test_unique_path_does_not_overwrite(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    assert unique_path(tmp_path, "a.wav").name == "a_2.wav"


def test_recorder_writes_a_readable_16_bit_stereo_wav(tmp_path):
    p = tmp_path / "r.wav"
    rec = WavRecorder(p, 48000)
    mono = _tone(secs=0.5)
    stereo = np.repeat(mono[:, None], 2, axis=1).astype("<f4")
    for i in range(0, len(stereo), 2048):
        rec.write(stereo[i:i + 2048].tobytes())
    rec.close()
    assert rec.frames == len(mono) and abs(rec.seconds - 0.5) < 1e-6
    with wave.open(str(p)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (2, 2, 48000, len(mono))
    data, rate = read_audio(p)
    assert rate == 48000 and data.shape == (len(mono), 2)
    assert np.abs(data[:, 0] - mono).max() < 1e-3                       # 16-bit quantisation only


def test_recorder_clips_instead_of_wrapping(tmp_path):
    rec = WavRecorder(tmp_path / "c.wav", 48000)
    rec.write(np.array([3.0, -3.0, 0.0, 0.0], dtype="<f4").tobytes())
    rec.close()
    data, _ = read_audio(tmp_path / "c.wav")
    assert data[0, 0] > 0.99 and data[0, 1] < -0.99


def _write_wav(path, tag, bits, rate, samples_bytes, channels=1, extensible=False):
    block = channels * bits // 8
    if extensible:
        fmt = struct.pack("<HHIIHHHHIH", 0xFFFE, channels, rate, rate * block, block, bits, 22, bits, 0, tag)
        fmt += b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    else:
        fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(samples_bytes))
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + len(samples_bytes)) + body + samples_bytes)


def test_read_audio_formats(tmp_path):
    x = np.array([0.0, 0.5, -0.5, 0.25], dtype=np.float32)
    cases = {
        "pcm8": (1, 8, ((x * 127) + 128).astype(np.uint8).tobytes()),
        "pcm16": (1, 16, (x * 32767).astype("<i2").tobytes()),
        "pcm32": (1, 32, (x * 2147483647).astype("<i4").tobytes()),
        "f32": (3, 32, x.astype("<f4").tobytes()),
        "f64": (3, 64, x.astype("<f8").tobytes()),
    }
    for name, (tag, bits, raw) in cases.items():
        p = tmp_path / (name + ".wav")
        _write_wav(p, tag, bits, 8000, raw)
        data, rate = read_audio(p)
        assert rate == 8000 and data.shape == (4, 1), name
        assert np.abs(data[:, 0] - x).max() < 0.02, name
    b24 = b"".join(int(v * 8388607).to_bytes(3, "little", signed=True) for v in x)
    _write_wav(tmp_path / "pcm24.wav", 1, 24, 8000, b24)
    assert np.abs(read_audio(tmp_path / "pcm24.wav")[0][:, 0] - x).max() < 1e-3
    _write_wav(tmp_path / "ext.wav", 3, 32, 8000, x.astype("<f4").tobytes(), extensible=True)
    assert np.abs(read_audio(tmp_path / "ext.wav")[0][:, 0] - x).max() < 1e-6


def test_read_audio_rejects_junk(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"not a wav at all")
    with pytest.raises(ValueError):
        read_audio(tmp_path / "a.wav")
    _write_wav(tmp_path / "adpcm.wav", 2, 4, 8000, b"\x00" * 8)
    with pytest.raises(ValueError):
        read_audio(tmp_path / "adpcm.wav")


def test_to_tx_stereo_resamples_and_mixes_down():
    st = to_tx_stereo(np.stack([_tone(8000, 1.0, 440), -_tone(8000, 1.0, 440)], axis=1), 8000)
    assert st.shape == (48000, 2) and abs(st).max() < 1e-4              # opposite channels cancel in the mono mix
    hi = to_tx_stereo(_tone(96000, 1.0, 1000)[:, None], 96000)
    assert hi.shape == (48000, 2) and 0.4 < np.abs(hi).max() < 0.55
    assert np.allclose(hi[:, 0], hi[:, 1])


def test_player_blocks_gain_tail_and_done():
    p = FilePlayer(_tone(48000, 0.1)[:, None], 48000, gain=0.5)
    assert p.total == 4800 and abs(p.seconds - 0.1) < 1e-9 and not p.done
    first = p.read_frames(2048)
    assert first.shape == (2048, 2) and first.dtype == np.float32
    assert np.abs(first).max() <= 0.26                                   # 0.5 amplitude x 0.5 gain
    p.gain = 1.0
    seen = 2048
    while not p.done:
        blk = p.read_frames(2048)
        seen += 2048
        assert blk.shape == (2048, 2)
    assert seen >= p.total + p.tail
    assert np.abs(p.read_frames(2048)).max() == 0.0                      # silence after the end
