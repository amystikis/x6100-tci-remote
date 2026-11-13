"""GUI tests run headless (QT_QPA_PLATFORM=offscreen) against the fake radio."""
import asyncio
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from x6100_remote.fakeradio import serve_fake  # noqa: E402
from x6100_remote.gui.main_window import MainWindow  # noqa: E402
from x6100_remote.gui.worker import TciWorker  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))     # keep QSettings out of the real home
    app = QApplication.instance() or QApplication([])
    worker = TciWorker()
    win = MainWindow(worker)
    win.show()
    radio, server = asyncio.run_coroutine_threadsafe(serve_fake(0), worker.loop).result(5)
    win.connect_to("ws://127.0.0.1:%d/" % server.sockets[0].getsockname()[1])

    def pump(cond, timeout=3.0):
        t = time.time()
        while not cond():
            app.processEvents()
            time.sleep(0.01)
            assert time.time() - t < timeout, "timed out"
        app.processEvents()

    pump(lambda: worker.state.ready)
    yield win, radio, pump
    win.close()


def test_shows_radio_state(env):
    win, radio, pump = env
    assert win.freq.freq == 7151000 and win._mode_buttons["lsb"].isChecked()
    assert "OpenX6X00" in win.info.text()


def test_band_button_and_rapid_tuning_accumulates(env):
    win, radio, pump = env
    win.pick_band("20")
    pump(lambda: win.state.freq == 14_200_000 and win.state.mode == "usb")
    assert win._band_buttons["20"].isChecked()
    win.tune_by(1000)
    win.tune_by(1000)                      # second step must build on the first, not on stale state
    pump(lambda: win.state.freq == 14_202_000)


def test_lock_blocks_tuning(env):
    win, radio, pump = env
    win.lock.click()
    pump(lambda: win.state.lock)
    win.tune_by(1000)
    time.sleep(0.2)
    assert radio.vfo[0] == 7151000


def test_ptt_is_ignored_until_transmit_is_enabled(env):
    win, radio, pump = env
    win.set_ptt(True)
    time.sleep(0.2)
    assert not radio.trx and not win._ptt_on


def test_ptt_keys_and_unkeys_when_enabled(env):
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: radio.trx)
    win.set_ptt(False)
    pump(lambda: not radio.trx)


def test_disabling_transmit_controls_unkeys(env):
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: radio.trx)
    win.tx_enable.setChecked(False)
    pump(lambda: not radio.trx)


def test_transmit_time_limit_auto_unkeys(env):
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    win.tx_limit.setValue(5)
    win.set_ptt(True)
    pump(lambda: radio.trx)
    win._tx_since -= 10                    # pretend 10 s have passed
    pump(lambda: not radio.trx)


def test_closing_the_window_unkeys(env):
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: radio.trx)
    win.close()
    deadline = time.time() + 3
    while radio.trx and time.time() < deadline:
        time.sleep(0.02)
    assert not radio.trx


def test_spectrum_flows_into_view_and_click_tunes(env):
    from x6100_remote.fakeradio import serve_fake_panel
    win, radio, pump = env
    panel, pserver = asyncio.run_coroutine_threadsafe(serve_fake_panel(radio, 0), win.w.loop).result(5)
    win.w.connect_panel("ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    pump(lambda: win.spectrum.frames >= 3)
    f = win.spectrum._frame
    assert f.center_hz == 7151000 and win.spectrum._passband == (win.state.filter_lo, win.state.filter_hi)
    win.spectrum.tune_to.emit(7_152_340)
    pump(lambda: win.state.freq == 7_152_340)
    pump(lambda: win.spectrum._frame.center_hz == 7_152_340)               # spectrum re-centres
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)


def test_panel_info_shows_in_window(env):
    from x6100_remote.fakeradio import serve_fake_panel
    win, radio, pump = env
    panel, pserver = asyncio.run_coroutine_threadsafe(serve_fake_panel(radio, 0), win.w.loop).result(5)
    win.w.connect_panel("ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    pump(lambda: len(win.w.info.spots) == 5 and win.cw_view.toPlainText() != "")
    assert "PWR" in win.status_strip.text() and "5 W" in win.status_strip.text() and "FT8" in win.status_strip.text()
    assert not win.status_strip.isHidden() and not win.cw_box.isHidden()
    assert "CQ CQ DE" in win.cw_view.toPlainText()
    assert len(win.spectrum._plan) == 4 and len(win.spectrum._spots) == 5
    win.spots_act.setChecked(False)
    assert win.spectrum.show_spots is False
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)
