"""Spectrum feed: frame parsing, the client against the fake panel server, and GUI integration."""
import asyncio
import os

import numpy as np
import pytest

from x6100_remote.fakeradio import FakeRadio, serve_fake_panel
from x6100_remote.spectrum import (ALLOWED_COMMANDS, HEADER_SIZE, PanelClient, SpectrumFrame,
                                   pack_frame, parse_frame)


def test_header_layout_matches_captured_frame():
    # first 24 bytes of a frame captured from a real radio (firmware v0.3.9)
    head = bytes([255, 255, 0, 4, 152, 29, 109, 0, 160, 134, 1, 0, 149, 196, 110, 0,
                  148, 151, 152, 151, 146, 140, 149, 151])
    f = parse_frame(head + bytes([150] * (1024 - 8)))
    assert (f.center_hz, f.span_hz, f.seq, len(f.bins)) == (7151000, 100000, 7259285, 1024)
    assert list(f.bins[:8]) == [148, 151, 152, 151, 146, 140, 149, 151]
    assert f.hz_per_bin == pytest.approx(97.65625)
    assert f.freq_at(512) == pytest.approx(7151000)


def test_parse_rejects_other_binary_frames():
    assert parse_frame(b"") is None
    assert parse_frame(bytes([32, 3, 224, 1, 0, 0, 0, 0, 255, 216]) + bytes(50_000)) is None   # JPEG screen frame
    good = pack_frame(14200000, 100000, 1, np.zeros(1024, dtype=np.uint8))
    assert parse_frame(good) is not None and len(good) == HEADER_SIZE + 1024
    assert parse_frame(good[:-1]) is None                                  # truncated


def test_pack_roundtrip():
    bins = np.arange(256, dtype=np.uint8)
    f = parse_frame(pack_frame(7_000_000, 50_000, 42, bins))
    assert (f.center_hz, f.span_hz, f.seq) == (7_000_000, 50_000, 42) and np.array_equal(f.bins, bins)


def test_client_sends_only_whitelisted_commands_and_receives_frames():
    async def body():
        radio = FakeRadio()
        panel, server = await serve_fake_panel(radio, 0)
        c = PanelClient("ws://127.0.0.1:%d/" % server.sockets[0].getsockname()[1], keepalive=0.1)
        got: list[SpectrumFrame] = []
        c.on_frame = got.append
        task = asyncio.ensure_future(c.run())
        try:
            for _ in range(200):
                if len(got) >= 5:
                    break
                await asyncio.sleep(0.02)
            assert len(got) >= 5
            assert got[0].center_hz == radio.vfo[0] and got[0].span_hz == 100_000
            assert [b.seq for b in got] == sorted(b.seq for b in got)
            await asyncio.sleep(0.25)                                       # keepalive pings
            assert panel.log[:2] == ["screen 0", "panel 1"]
            assert set(panel.log) <= set(ALLOWED_COMMANDS) and "ping 1" in panel.log
        finally:
            await c.close()
            task.cancel()
            server.close()
            await server.wait_closed()
    asyncio.run(body())


def test_client_refuses_other_commands():
    async def body():
        c = PanelClient("ws://127.0.0.1:1/")
        with pytest.raises(ValueError):
            await c._send("key POWER")
    asyncio.run(body())


def test_spectrum_follows_fake_vfo():
    async def body():
        radio = FakeRadio()
        _, server = await serve_fake_panel(radio, 0)
        c = PanelClient("ws://127.0.0.1:%d/" % server.sockets[0].getsockname()[1])
        got: list[SpectrumFrame] = []
        c.on_frame = got.append
        task = asyncio.ensure_future(c.run())
        try:
            await asyncio.sleep(0.3)
            radio.vfo[0] = 14_200_000
            await asyncio.sleep(0.3)
            assert got[0].center_hz == 7_151_000 and got[-1].center_hz == 14_200_000
        finally:
            await c.close()
            task.cancel()
            server.close()
            await server.wait_closed()
    asyncio.run(body())


# ---- GUI -----------------------------------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from x6100_remote.gui.spectrum_view import Leveler, SpectrumView, nice_step  # noqa: E402
from x6100_remote.gui.settings import panel_url_for  # noqa: E402


def test_panel_url_for():
    assert panel_url_for("ws://192.168.0.150:50001/") == "ws://192.168.0.150:50002/"
    assert panel_url_for("ws://radio.local/") == "ws://radio.local:50002/"


def test_nice_step_and_leveler():
    assert nice_step(100_000) == 20_000 or nice_step(100_000) == 10_000
    lv = Leveler()
    out = lv.update(np.full(1024, 140, dtype=np.uint8))
    assert out.min() >= 0 and out.max() <= 1
    sig = np.full(1024, 140, dtype=np.uint8)
    sig[500] = 190
    assert Leveler().update(sig)[500] > 0.9


def test_waterfall_shifts_when_vfo_changes(qapp=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=8)
    bins = np.full(1024, 140, dtype=np.uint8)
    bins[300] = 200
    v.push(SpectrumFrame(7_000_000, 100_000, 1, bins))
    marked = int(np.argmax(v._wf[0]))
    assert marked == 300
    hz_per_bin = 100_000 / 1024
    v.push(SpectrumFrame(7_000_000 + round(50 * hz_per_bin), 100_000, 2, np.full(1024, 140, dtype=np.uint8)))
    # the old strong signal is now 50 bins further left, in the row below the new one
    assert int(np.argmax(v._wf[1])) == 250
    v.resize(600, 400)
    v.grab()                                                               # paints without error
