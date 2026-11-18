"""Spectrum feed: frame parsing, the client against the fake panel server, and GUI integration."""
import asyncio
import os

import numpy as np
import pytest

from x6100_remote.fakeradio import FakeRadio, serve_fake_panel
from x6100_remote.spectrum import (HEADER_SIZE, KEY_NAMES, ControlDenied, PanelClient, SpectrumFrame,
                                   is_allowed, pack_frame, parse_frame)


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
            assert all(is_allowed(m) for m in panel.log) and "ping 1" in panel.log
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


# ---- panel info (bands, plan, spots, state, cw) -----------------------------------------------------
from x6100_remote.panelinfo import PanelInfo, merge_cw  # noqa: E402

# lines copied from a real radio (firmware v0.3.9)
REAL_SPOTS = ('spots [{"f":7043000,"c":"AC4WW","m":"CW","a":0,"s":"WB6BEE-#","k":"POTA US-9774 CW","al":0},'
              '{"f":7183000,"c":"AC1RH","m":"SSB","a":0,"s":"VA2YH","k":"POTA US-0449 SSB","al":0}]')
REAL_STATE = ('state {"freq":7174000,"mode":0,"flo":50,"fhi":3050,"kt":700,"agc":0,"pre":1,"att":0,"nb":0,"nr":0,'
              '"sql":0,"rfg":70,"vol":0,"pwr":2.5,"step":500,"zoom":4,"vfo":0,"atu":0,"bat":-1,"tx":0,"lock":0,'
              '"tune":0,"tune_s":15,"ulock":0,"cwrise":0}')


def test_panelinfo_parses_real_lines():
    i = PanelInfo()
    assert i.apply(REAL_SPOTS) == "spots" and len(i.spots) == 2
    s = i.spots[0]
    assert (s.freq, s.call, s.mode, s.age, s.spotter, s.comment, s.alert) == (
        7043000, "AC4WW", "CW", 0, "WB6BEE-#", "POTA US-9774 CW", False)
    assert i.spots_in(7_100_000, 7_200_000)[0].call == "AC1RH"
    assert i.apply('plan [[1810000,1838000,0],[1838000,1843000,1],[1843000,2000000,2]]') == "plan"
    assert [(p.lo, p.kind) for p in i.plan] == [(1810000, 0), (1838000, 1), (1843000, 2)]
    assert i.apply('bands [{"n":"160m","a":1810000,"b":2000000}]') == "bands" and i.bands[0].name == "160m"
    assert i.apply(REAL_STATE) == "state" and i.battery is None
    labels = {k: (v, on) for k, v, on in i.status_items()}
    assert labels["PRE"] == ("1", True) and labels["NB"] == ("off", False) and labels["PWR"] == ("2.5 W", True)
    assert "BAT" not in labels                                              # bat -1 = unknown
    i.apply('state {"bat":18}')
    assert dict((k, on) for k, _, on in i.status_items())["BAT"] is True    # low battery highlighted
    assert i.apply('ft8 {"open":0,"tx":0}') == "ft8" and i.ft8["open"] == 0


def test_panelinfo_ignores_junk():
    i = PanelInfo()
    for line in ("m -101.5", "spots not-json", 'plan [[1,2]]', "bands [{}]", "", "keys POWER GEN", "unknown 1"):
        assert i.apply(line) is None
    assert i.spots == [] and i.plan == [] and i.bands == []


def test_merge_cw_handles_increments_and_full_buffers():
    assert merge_cw("", "CQ ") == "CQ "
    assert merge_cw("CQ CQ ", "DE K1TTT ") == "CQ CQ DE K1TTT "          # increments
    assert merge_cw("CQ CQ ", "CQ CQ DE K1") == "CQ CQ DE K1"            # growing buffer
    assert merge_cw("CQ CQ DE K1", "CQ CQ DE K1") == "CQ CQ DE K1"       # repeat
    assert len(merge_cw("x" * 5000, "abc")) <= 4000


def test_client_collects_info_from_fake_panel():
    async def body():
        radio = FakeRadio()
        _, server = await serve_fake_panel(radio, 0)
        c = PanelClient("ws://127.0.0.1:%d/" % server.sockets[0].getsockname()[1])
        kinds: list[str] = []
        c.on_info = kinds.append
        task = asyncio.ensure_future(c.run())
        try:
            for _ in range(100):
                if "spots" in kinds:
                    break
                await asyncio.sleep(0.02)
            assert {"bands", "plan", "state", "ft8", "cw", "spots"} <= set(kinds)
            assert c.info.hello.startswith("OpenX6X00") and len(c.info.spots) == 5
        finally:
            await c.close()
            task.cancel()
            server.close()
            await server.wait_closed()
    asyncio.run(body())


def test_spot_layout_hit_testing_and_band_plan():
    from PySide6.QtWidgets import QApplication
    from x6100_remote.panelinfo import PlanSegment, Spot
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=8)
    v.resize(800, 500)
    v.push(SpectrumFrame(7_150_000, 100_000, 1, np.full(1024, 140, dtype=np.uint8)))
    v.set_plan([PlanSegment(7_000_000, 7_040_000, 0), PlanSegment(7_060_000, 7_200_000, 2)])
    v.set_spots([Spot(7_150_400, "AC4WW", "CW"), Spot(7_150_900, "SP9XYZ", "SSB"), Spot(8_000_000, "FAR", "CW")])
    v.grab()
    calls = {s.call for _, s in v._spot_boxes}
    assert calls == {"AC4WW", "SP9XYZ"}                                     # out-of-view spot not drawn
    box, spot = v._spot_boxes[0]
    hit = v.spot_at(box.center().x(), box.center().y())
    assert hit is spot and v.spot_at(5, 400) is None
    tuned = []
    v.tune_to.connect(tuned.append)
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    pos = QPointF(box.center().x() + 3, box.center().y())
    v.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
                                  Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert tuned == [spot.freq]                                             # exact spot frequency, not snapped
    v.set_show_spots(False)
    v.grab()
    assert v._spot_boxes == [] and v.spot_at(box.center().x(), box.center().y()) is None


# ---- keys, pairing, role gating ----------------------------------------------------------------------
def test_whitelist_never_allows_power_or_ptt():
    for ok in ("screen 0", "panel 1", "ping 1", "control take", "control release", "pair?", "key PRE 1", "key ATU 0",
               "pair 123456 my-app", "auth " + "ab" * 16):
        assert is_allowed(ok), ok
    for bad in ("key POWER 1", "key PTT 1", "key KEY 1", "key MFK 1", "key PRE 2", "key PRE", "screen 1",
                "pair 12345 x", "pair 123456", "pair ?", "auth zz", "control grab", "key PRE 1; key POWER 1",
                "key  PRE 1"):
        assert not is_allowed(bad), bad
    assert set(KEY_NAMES) == {"PRE", "AB", "VM", "FST", "ATU"}


async def _with_panel(body):
    radio = FakeRadio()
    panel, server = await serve_fake_panel(radio, 0)
    url = "ws://127.0.0.1:%d/" % server.sockets[0].getsockname()[1]
    try:
        await body(panel, url)
    finally:
        server.close()
        await server.wait_closed()


async def _run_client(url, token=None):
    c = PanelClient(url, token=token)
    task = asyncio.ensure_future(c.run())
    for _ in range(100):
        if c.info.hello:
            break
        await asyncio.sleep(0.02)
    return c, task


def test_unpaired_client_cannot_press_keys():
    async def body(panel, url):
        c, task = await _run_client(url)
        try:
            assert c.info.role == "view"
            with pytest.raises(ControlDenied):
                await c.press("PRE")
            with pytest.raises(ValueError):
                await c.press("POWER")
            await asyncio.sleep(0.1)
            assert not any(m.startswith(("key", "control")) for m in panel.log) and panel.keys_pressed == []
        finally:
            await c.close()
            task.cancel()
    asyncio.run(_with_panel(body))


def test_pairing_then_key_press_changes_radio_state():
    async def body(panel, url):
        c, task = await _run_client(url)
        paired = []
        c.on_paired = lambda role, key: paired.append((role, key))
        try:
            await c.pair("123456", "x")                                   # no code requested yet: nothing happens
            await asyncio.sleep(0.15)
            assert paired == [] and c.info.role == "view"
            await c.request_pair_code()                                   # "pair?": the radio shows the code
            await c.pair("000000", "x")                                   # wrong code: nothing happens
            await asyncio.sleep(0.15)
            assert paired == [] and c.info.role == "view"
            await c.pair("123456", "test-app")
            for _ in range(100):
                if paired:
                    break
                await asyncio.sleep(0.02)
            assert paired == [("operate", panel.TOKEN)]
            await asyncio.sleep(0.1)
            assert c.info.role == "operate" and c.info.tx_allowed
            before = c.info.state["pre"]
            await c.press("PRE")
            await asyncio.sleep(0.2)
            assert panel.keys_pressed == ["PRE"] and c.info.state["pre"] == (before + 1) % 3
            assert panel.log[-3:] == ["key PRE 1", "key PRE 0", "control release"]
        finally:
            await c.close()
            task.cancel()
    asyncio.run(_with_panel(body))


def test_saved_key_authenticates_a_new_connection():
    async def body(panel, url):
        c, task = await _run_client(url, token=panel.TOKEN)
        try:
            for _ in range(100):
                if c.info.role == "operate":
                    break
                await asyncio.sleep(0.02)
            assert c.info.role == "operate" and panel.log[0] == "auth " + panel.TOKEN
        finally:
            await c.close()
            task.cancel()
        c2, task2 = await _run_client(url, token="not-hex!")                 # malformed key is dropped, not sent
        try:
            assert c2.token is None and c2.info.role == "view"
        finally:
            await c2.close()
            task2.cancel()
    asyncio.run(_with_panel(body))


def test_spectrum_colours_include_red():
    pytest.importorskip("PySide6")
    from x6100_remote.gui.spectrum_view import SPECTRUM_SCHEMES
    assert SPECTRUM_SCHEMES["Red"] == "#ff5a5a"
