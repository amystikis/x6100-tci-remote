"""GUI tests run headless (QT_QPA_PLATFORM=offscreen) against the fake radio."""
import asyncio
import re
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
    assert not win.status_strip.isHidden()
    assert win.cw_box.isHidden()                                       # LSB: CW box hidden even with text
    win.w.send("modulation", 0, "cw")
    pump(lambda: not win.cw_box.isHidden())                            # CW mode: shown
    win.w.send("modulation", 0, "usb")
    pump(lambda: win.cw_box.isHidden())
    win.w.send("modulation", 0, "cw")
    pump(lambda: not win.cw_box.isHidden())
    assert "CQ CQ DE" in win.cw_view.toPlainText()
    assert win.cw_view.height() == 78
    assert len(win.spectrum._plan) == 4 and len(win.spectrum._spots) == 5
    win.spots_act.setChecked(False)
    assert win.spectrum.show_spots is False
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)


def test_key_buttons_need_pairing_and_atu_tune_needs_tx_enable(env):
    from x6100_remote.fakeradio import serve_fake_panel
    win, radio, pump = env
    assert all(not b.isEnabled() for b in win._key_buttons.values())      # no panel connection yet
    panel, pserver = asyncio.run_coroutine_threadsafe(serve_fake_panel(radio, 0), win.w.loop).result(5)
    win.w.connect_panel("ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    pump(lambda: win._key_buttons["PRE"].isEnabled() and win.w.info.hello)
    assert not win.pair_btn.isHidden() and not win.atu_tune.isEnabled()
    win._key_buttons["PRE"].click()                                        # unpaired: refused, nothing sent
    pump(lambda: "not paired" in win.statusBar().currentMessage())
    assert not any(m.startswith(("key", "control")) for m in panel.log)
    win.w.pair_panel("123456", "gui-test")                                 # no code was requested yet: refused
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.2), win.w.loop).result(2)
    assert win.w.info.role == "view" and win.w.info.state.get("pre") is not None
    from PySide6.QtWidgets import QInputDialog
    QInputDialog.getText = staticmethod(lambda *a, **k: ("123456", True))
    win.pair_panel()                                                       # real flow: pair? then the typed code
    pump(lambda: "pair?" in panel.log                                       # code request, then a pair message after it
         and any(m.startswith("pair 123456") for m in panel.log[panel.log.index("pair?"):]))
    pump(lambda: win.w.info.role == "operate" and win.pair_btn.isHidden())
    pump(lambda: "Paired as operate" in win.statusBar().currentMessage())
    pre_before = panel.pre
    win._key_buttons["PRE"].click()
    pump(lambda: panel.keys_pressed == ["PRE"])
    pump(lambda: win.w.info.state.get("pre") == (pre_before + 1) % 3)
    pump(lambda: panel.log[-1] == "control release")                       # press finished with key-up + release
    assert panel.log[-3:-1] == ["key PRE 1", "key PRE 0"]
    assert win._key_buttons["ATU"].property("on") is True                  # ATU shown on (fake state atu=1)
    assert not win.atu_tune.isEnabled()                                    # transmit controls still off
    win.tx_enable.setChecked(True)
    pump(lambda: win.atu_tune.isEnabled())
    win.tx_enable.setChecked(False)
    pump(lambda: not win.atu_tune.isEnabled())
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)


def test_view_menu_toggles_groups_and_remembers(env):
    win, radio, pump = env
    for key, box in (("band", win.band_box), ("mode", win.modes_box), ("receiver", win.rx_box),
                     ("audio", win.audio_box)):
        act = getattr(win, "view_%s_act" % key)
        assert act.isChecked() and not box.isHidden()
        act.setChecked(False)
        assert box.isHidden()
        act.setChecked(True)
        assert not box.isHidden()
    win.view_audio_act.setChecked(False)
    from x6100_remote.gui.settings import load_flag
    assert load_flag("show_audio") is False and load_flag("show_band") is True
    win.view_audio_act.setChecked(True)


def _cli(pump, name, *args, code=None):
    """Run `python -m x6100_remote ...` like an OS keyboard shortcut would; pump Qt events until it finishes."""
    import subprocess
    import sys
    env = dict(os.environ, X6100_TCI_REMOTE_IPC=name, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))
    cmd = [sys.executable, "-m", "x6100_remote", *args] if code is None else [sys.executable, "-c", code]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pump(lambda: p.poll() is not None, 15)
    out, err = p.communicate()
    return p.returncode, (out + err).strip()


def test_os_hotkey_ptt_via_command_line(env):
    import uuid

    from PySide6.QtCore import QEvent
    win, radio, pump = env
    name = "x6100-test-" + uuid.uuid4().hex[:8]
    assert win.start_command_server(name) is True
    assert _cli(pump, name, "--ptt", "on") == (1, "refused: 'Enable transmit controls' is not ticked in the app")
    assert not radio.trx
    win.tx_enable.setChecked(True)
    win.isActiveWindow = lambda: False                                     # the window has lost focus
    assert _cli(pump, name, "--ptt", "on") == (0, "ok: transmitting")
    pump(lambda: radio.trx)
    win.changeEvent(QEvent(QEvent.Type.ActivationChange))                  # hotkey PTT stays on
    assert win._ptt_on and radio.trx
    assert _cli(pump, name, "--ptt", "toggle") == (0, "ok: receive")
    pump(lambda: not radio.trx)
    assert _cli(pump, name, "--ptt", "toggle") == (0, "ok: transmitting")
    pump(lambda: radio.trx)
    assert _cli(pump, name, "--ptt", "off") == (0, "ok: receive")         # off always works
    pump(lambda: not radio.trx)
    win.set_ptt(True)                                                      # button PTT still drops on focus loss
    pump(lambda: radio.trx)
    win.changeEvent(QEvent(QEvent.Type.ActivationChange))
    pump(lambda: not radio.trx)
    win.cmd_server.stop()
    rc, msg = _cli(pump, name, "--ptt", "on")
    assert rc == 1 and "not running" in msg                                # no app: clear error, non-zero exit


def test_second_instance_does_not_steal_the_hotkey_socket(env):
    import uuid
    win, radio, pump = env
    name = "x6100-test-" + uuid.uuid4().hex[:8]
    assert win.start_command_server(name) is True
    code = ("from PySide6.QtCore import QCoreApplication; import sys; app = QCoreApplication(sys.argv[:1]); "
            "from x6100_remote.ipc import CommandServer; print(CommandServer(lambda c: 'x', %r).start())" % name)
    assert _cli(pump, name, code=code) == (0, "False")
    win.cmd_server.stop()


def test_drive_slider_sends_on_wheel_keys_click_and_drag(env):
    from PySide6.QtWidgets import QSlider
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    start = radio.drive
    win.drive.setValue(start + 7)                                            # what a wheel notch / click does
    pump(lambda: radio.drive == start + 7)
    win.drive.triggerAction(QSlider.SliderAction.SliderSingleStepAdd)        # arrow key
    pump(lambda: radio.drive == start + 8)
    for v in range(10, 61, 5):                                               # a fast scroll: many changes at once
        win.drive.setValue(v)
    pump(lambda: radio.drive == 60)                                          # the last value always arrives
    sent = [m for m in radio.log if m.startswith("drive")]
    assert len(sent) < 14                                                    # throttled, not one message per step
    pump(lambda: win.drive.value() == 60 and win.drive_lbl.text() == "6.0 W")   # the radio's echo does not undo it
    win.drive.setValue(61)
    win.drive.sliderReleased.emit()                                          # release sends at once
    pump(lambda: radio.drive == 61)


def test_cw_modes_centre_the_passband_and_enable_the_tuner(env):
    from x6100_remote.fakeradio import serve_fake_panel
    win, radio, pump = env
    panel, pserver = asyncio.run_coroutine_threadsafe(serve_fake_panel(radio, 0), win.w.loop).result(5)
    win.w.connect_panel("ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    pump(lambda: win.spectrum.frames >= 2)
    assert win.spectrum._cw_bw is None and win.spectrum._passband == (win.state.filter_lo, win.state.filter_hi)
    win.w.send("modulation", 0, "cw")
    win.w.send("rx_filter_band", 0, 350, 1050)                              # a 700 Hz CW filter around a 700 Hz pitch
    pump(lambda: win.state.mode == "cw" and win.state.filter_hi == 1050)
    pump(lambda: win.spectrum._cw_bw == 700)
    assert win.spectrum._passband == (350, 1050)  # one pitch above the VFO
    pump(lambda: win.spectrum._cw_tune is not None)                         # the fake CW signal (~70 Hz above the VFO)
    n = win.spectrum.frames
    pump(lambda: win.spectrum.frames >= n + 25, 6)                          # let the smoothing settle
    assert 45 < win.spectrum._cw_tune.offset_hz < 95
    win.w.send("modulation", 0, "cwr")
    pump(lambda: win.state.mode == "cwr")
    assert win.spectrum._cw_bw == 700
    win.cw_tuner_act.setChecked(False)
    assert win.spectrum.show_cw_tuner is False
    win.cw_tuner_act.setChecked(True)
    win.w.send("modulation", 0, "usb")
    win.w.send("rx_filter_band", 0, 50, 2850)
    pump(lambda: win.state.mode == "usb" and win.state.filter_hi == 2850)
    pump(lambda: win.spectrum._cw_bw is None)
    assert win.spectrum._passband == (50, 2850)
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)


def test_zoom_and_colour_schemes(env):
    from x6100_remote.fakeradio import serve_fake_panel
    from x6100_remote.gui.spectrum_view import SPECTRUM_SCHEMES, WATERFALL_SCHEMES, ZOOM_LEVELS
    win, radio, pump = env
    panel, pserver = asyncio.run_coroutine_threadsafe(serve_fake_panel(radio, 0), win.w.loop).result(5)
    win.w.connect_panel("ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    assert [win.zoom.itemData(i) for i in range(win.zoom.count())] == list(ZOOM_LEVELS) == [1, 2, 4, 8]
    pump(lambda: win.spectrum._frame is not None)
    sv = win.spectrum
    f = sv._frame
    win.zoom.setCurrentIndex(win.zoom.findData(4))
    assert sv._zoom == 4
    assert sv._x_of(f.center_hz + f.span_hz / 8) == pytest.approx(sv.width())      # visible span is 1/4
    assert sv._hz_at(sv.width() / 2) == pytest.approx(f.center_hz)
    sv.grab()                                                                       # paints at zoom without error
    before = sv._wf.copy()
    sv.set_waterfall_scheme("Grayscale")
    assert "Grayscale" in WATERFALL_SCHEMES and not (sv._wf == before).all()        # history is recoloured
    sv.set_spectrum_scheme("Amber")
    assert sv._trace_color.name() == SPECTRUM_SCHEMES["Amber"]
    sv.grab()
    win.w.disconnect_panel()
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), win.w.loop).result(2)


def test_clock_connection_settings_and_status_bar(env):
    win, _radio, _pump = env
    assert re.fullmatch(r"\d\d:\d\d:\d\d", win.clock.text()) and win.utc_lbl.text() == "UTC"
    assert win.addr.window() is win.settings_dlg and win.connect_btn.window() is win.settings_dlg
    assert win.settings_tabs.tabText(0) == "Connection"
    assert win.status.parent() is win.statusBar()


def test_autoconnect_to_the_last_radio_and_zoom_starts_at_1x(env):
    from x6100_remote.gui.settings import remember_radio
    win, _radio, pump = env
    ok = MainWindow.valid_radio_address
    assert ok("192.168.0.150") and ok("192.168.0.150:50001") and ok("ws://radio.local:50001/") and ok("x6100")
    assert not ok("") and not ok("999.1.1.1") and not ok("1.2.3.4:99999") and not ok("bad host") and not ok("a..b")
    assert win.zoom.currentData() == 1
    _r, server = asyncio.run_coroutine_threadsafe(serve_fake(0), win.w.loop).result(5)
    remember_radio("127.0.0.1:%d" % server.sockets[0].getsockname()[1])
    win2 = MainWindow(TciWorker())
    assert win2.zoom.currentData() == 1
    assert win2.auto_connect_last()
    pump(lambda: win2.w.state.ready)
    win2.w.disconnect_from()
    win2.close()
    remember_radio("not a valid address!")
    win3 = MainWindow(TciWorker())
    assert not win3.auto_connect_last() and win3.connect_btn.text() == "Connect"
    win3.close()


def test_transmit_box_can_be_hidden_and_is_remembered(env):
    win, radio, pump = env
    assert win.tx_box.isVisible()
    win.view_transmit_act.setChecked(False)
    assert not win.tx_box.isVisible() and not win.ptt.isVisible()
    from x6100_remote.gui.settings import load_flag
    assert load_flag("show_transmit") is False
    win.view_transmit_act.setChecked(True)
    assert win.tx_box.isVisible()


def test_themes_switch_and_are_remembered(env):
    from x6100_remote.gui import widgets
    from x6100_remote.gui.settings import load_choice
    from x6100_remote.gui.themes import THEMES
    win, radio, pump = env
    assert {"Light", "Dark", "Midnight", "Night red"} <= set(THEMES)
    for name, theme in THEMES.items():
        win.set_theme(name)
        assert theme.bg in win.styleSheet() and widgets.AMBER.name() == theme.accent
        assert load_choice("theme", "") == name
    win.set_theme("nonsense")                      # unknown names are ignored
    assert win.theme_name == "Night red"
    win.set_theme("Midnight")


def test_cw_clear_stays_cleared(env):
    win, radio, pump = env
    win.w.info.cw_text = "CQ CQ DE M7SVA"
    win.on_panel_info("cw")
    assert "CQ" in win.cw_view.toPlainText()
    win.clear_cw()
    win.on_panel_info("cw")                      # the next message must not bring the old text back
    assert win.cw_view.toPlainText() == "" and win.w.info.cw_text == ""


def test_am_passband_is_drawn_on_both_sides(env):
    win, radio, pump = env
    win.state.mode, win.state.filter_lo, win.state.filter_hi = "am", 0, 6000
    win.refresh("filter")
    assert win.spectrum._passband == (-6000, 6000)
    win.state.mode, win.state.filter_lo, win.state.filter_hi = "usb", 300, 2700
    win.refresh("filter")
    assert win.spectrum._passband == (300, 2700)


def test_spectrum_trace_auto_floor(env):
    import numpy as np
    win, radio, pump = env
    sp = win.spectrum
    level = np.full(100, 0.3, dtype=np.float32)
    level[50] = 0.9
    sp._tr_med = 0.3
    sp.set_trace_floor(True, 0.0)
    y = sp._trace_levels(level)
    assert y[0] == 0.0 and y[50] > 0.8                  # noise sits at the bottom, the signal stands out
    sp.set_trace_floor(False, 0.0)
    assert sp._trace_levels(level)[0] == pytest.approx(0.3)


def test_fullscreen_toggle(env):
    win, radio, pump = env
    win.toggle_fullscreen()
    assert win.isFullScreen() and win.fullscreen_act.isChecked() and "Exit" in win.fullscreen_btn.text()
    win.toggle_fullscreen()
    assert not win.isFullScreen() and not win.fullscreen_act.isChecked()


def test_connect_button_and_pair_state_in_connection_settings(env):
    win, radio, pump = env
    pump(lambda: win.connect_btn.text() == "Disconnect")
    assert win.pair_btn2.window() is win.settings_dlg
    win.on_status("disconnected", "")
    assert win.connect_btn.text() == "Connect"
    win.on_status("connected", "")
    assert win.connect_btn.text() == "Disconnect"
    win._panel_up = True
    win._update_pair_state()
    assert win.pair_btn2.isEnabled() and "Not paired" in win.pair_state.text()


def test_spot_colour_choice(env):
    win, radio, pump = env
    win._spot_scheme_chosen("Red")
    assert win.spectrum._spot_color == "#ff5a5a"
    win._spot_scheme_chosen("By mode")
    assert win.spectrum._spot_color is None


def test_tx_meter_popup_shows_only_while_transmitting(env):
    win, radio, pump = env
    assert not win.tx_meter.isVisible()
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: win.tx_meter.isVisible())
    win.w.info.apply("t 3.0 2.40 5.0")
    win._tx_meter_update()
    assert win.tx_meter._vals["PWR"].text() == "3.0 W" and win.tx_meter._vals["SWR"].text() == "2.40"
    win.set_ptt(False)
    pump(lambda: not win.tx_meter.isVisible())


def test_waterfall_keeps_scrolling_and_dims_while_transmitting(env):
    win, radio, pump = env
    sp = win.spectrum
    import numpy as np
    from x6100_remote.spectrum import SpectrumFrame
    bins = np.full(1024, 140, dtype=np.uint8)
    bins[500:520] = 230                                    # a strong signal, so the pushed row is not blank
    sp.push(SpectrumFrame(7_151_000, 100_000, 1, bins))
    assert not (sp._wf[0] == sp._bg).all()
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: sp._tx)
    pump(lambda: (sp._wf[0] == sp._bg).all())              # the timer scrolls in empty rows
    win.set_ptt(False)
    pump(lambda: not sp._tx)


def test_tx_meter_shows_elapsed_time_and_power_label_is_watts(env):
    win, radio, pump = env
    assert win.drive.minimum() == 0 and win.drive.maximum() == 100
    for drive, watts in ((0, "0.1 W"), (1, "0.2 W"), (10, "1.1 W"), (100, "10.0 W")):    # as the radio shows them
        win.drive.setValue(drive)
        assert win.drive_lbl.text() == watts
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: win.tx_meter.isVisible())
    t = time.time()
    pump(lambda: win.tx_meter._clock.text() != "00:00.0", 2)
    win.set_ptt(False)
    pump(lambda: not win.tx_meter.isVisible())
    assert not win.tx_meter._tick.isActive() and time.time() - t < 2


def test_space_holds_ptt_wherever_the_focus_is(env):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication as App
    win, radio, pump = env
    win.activateWindow()
    pump(lambda: App.activeWindow() is win)
    win.tx_enable.setChecked(False)
    win.tx_enable.setFocus()

    def key(kind, auto=False):
        ev = QKeyEvent(kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ", auto)
        return win.eventFilter(win.tx_enable, ev)

    assert key(QEvent.Type.KeyPress) and not win._ptt_on and not win.tx_enable.isChecked()   # refused, not toggled
    win.tx_enable.setChecked(True)
    assert key(QEvent.Type.KeyPress) and win._ptt_on and win.ptt.isDown()                    # button shows keyed
    assert key(QEvent.Type.KeyPress, auto=True) and win._ptt_on                              # auto-repeat does nothing
    assert key(QEvent.Type.KeyRelease) and win._ptt_on                       # release is debounced
    assert key(QEvent.Type.KeyPress) and win._ptt_on                         # key repeat: release+press
    assert key(QEvent.Type.KeyRelease)
    pump(lambda: not win._ptt_on and not win.ptt.isDown())                    # a real release unkeys


def test_ptt_key_can_be_changed_and_disabled(env):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent, QKeySequence
    from PySide6.QtWidgets import QApplication as App
    win, radio, pump = env
    win.activateWindow()
    pump(lambda: App.activeWindow() is win)
    win.tx_enable.setChecked(True)

    def key(k, kind):
        return win.eventFilter(win, QKeyEvent(kind, k, Qt.KeyboardModifier.NoModifier, "x", False))

    win.ptt_key_edit.setKeySequence(QKeySequence(Qt.Key.Key_F9))
    assert win._ptt_key == Qt.Key.Key_F9.value
    assert not key(Qt.Key.Key_Space, QEvent.Type.KeyPress) and not win._ptt_on          # old key does nothing now
    assert key(Qt.Key.Key_F9, QEvent.Type.KeyPress) and win._ptt_on
    win.ptt_key_check.setChecked(False)                                                 # disabling unkeys at once
    assert not win._ptt_on
    assert not key(Qt.Key.Key_F9, QEvent.Type.KeyPress) and not win._ptt_on
    win.ptt_key_check.setChecked(True)
    win.ptt_key_edit.setKeySequence(QKeySequence(Qt.Key.Key_Left))                      # reserved: refused, key kept
    assert win._ptt_key == Qt.Key.Key_F9.value


def test_tx_meter_colours_follow_swr(env):
    win, radio, pump = env
    m = win.tx_meter

    def swr_colour(v):
        m.update_values(2.0, v, 3.0)
        return m._bars["SWR"].property("chunk")

    assert swr_colour(1.3) == m.COL_SWR_OK and swr_colour(2.0) == m.COL_SWR_OK
    assert swr_colour(2.3) == m.COL_AMBER and swr_colour(2.49) == m.COL_AMBER
    assert swr_colour(2.5) == m.COL_RED and swr_colour(3.5) == m.COL_RED
    assert m._bars["PWR"].property("chunk") == m.COL_PWR and m._bars["ALC"].property("chunk") == m.COL_ALC


def test_app_follows_the_radio_ending_a_transmission(env):
    win, radio, pump = env
    win.tx_enable.setChecked(True)
    win.set_ptt(True)
    pump(lambda: win.state.trx)
    win._tx_since -= 5                                    # keyed a while ago
    asyncio.run_coroutine_threadsafe(radio.broadcast("trx:0,false;"), win.w.loop).result(3)
    pump(lambda: not win._ptt_on)
    assert "radio ended" in win.statusBar().currentMessage()


def test_mode_follows_band_and_segment(env):
    win, radio, pump = env
    from x6100_remote.panelinfo import PlanSegment
    win.w.info.plan = [PlanSegment(7_000_000, 7_040_000, 0), PlanSegment(7_040_000, 7_060_000, 1),
                       PlanSegment(7_060_000, 7_200_000, 2)]            # 40 m: CW, digital, phone
    win._auto_mode(win.state.freq, apply=False)
    assert win.state.mode == "lsb" and win.freq.freq == 7_151_000
    win.tune_by(-131_000)                                           # 7.020 MHz: CW segment
    pump(lambda: win.state.mode == "cw")
    win.tune_by(30_000)                                             # 7.050 MHz: digital segment
    pump(lambda: win.state.mode == "digu")
    win.tune_by(-30_000)                                            # CW again, then a manual choice stays inside it
    pump(lambda: win.state.mode == "cw")
    win.w.send("modulation", 0, "usb")
    pump(lambda: win.state.mode == "usb")
    win.tune_by(1000)
    pump(lambda: win.state.freq == 7_021_000)
    time.sleep(0.3)
    assert win.state.mode == "usb"                                  # same segment: not overridden
    win.band_mem.update({"20": [14_200_000, "usb"], "80": [3_700_000, "lsb"]})     # not what earlier tests left
    win.pick_band("20")                                             # 14.200 MHz: USB; 40 m phone is LSB
    pump(lambda: win.state.mode == "usb" and win.state.freq == 14_200_000)
    win.pick_band("80")
    pump(lambda: win.state.mode == "lsb" and win.state.freq == 3_700_000)
    win.auto_mode_check.setChecked(False)
    win.w.send("modulation", 0, "usb")
    pump(lambda: win.state.mode == "usb")
    win.band_mem["40"] = [7_100_000, "lsb"]
    win.pick_band("40")
    pump(lambda: win.state.freq == 7_100_000 and win.state.mode == "lsb")   # remembered mode is used, auto mode off


def test_recorder_writes_the_radios_audio_to_a_wav_file(env, tmp_path):
    import wave
    from x6100_remote.gui.settings import save_choice
    win, radio, pump = env
    save_choice("rec_dir", str(tmp_path))
    assert not win.sound.isChecked()
    win.rec_btn.setChecked(True)                                   # Sound is off: REC starts the audio stream itself
    pump(lambda: win._rec is not None and win._rec.frames > 48000 * 0.3)
    assert win._rec_started_audio and win.rec_time.text() == "00:00"
    name = win._rec.path.name
    assert name.startswith("x6100_") and "kHz_LSB" in name and name.endswith(".wav")
    win.rec_btn.setChecked(False)
    assert win._rec is None and not win._recording
    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0])) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 48000) and w.getnframes() > 10000
    pump(lambda: not win._rec_started_audio)                       # and the stream it started is switched off again
    assert "Saved" in win.statusBar().currentMessage()


def test_recording_needs_a_connection(env):
    from unittest.mock import patch
    win, radio, pump = env
    with patch.object(win.w, "client", None):                      # restored before the fixture shuts the window down
        win.rec_btn.setChecked(True)
        assert not win.rec_btn.isChecked() and not win._recording
    pump(lambda: win.w.client is not None)


def _tone_wav(path, secs=0.4):
    import wave
    import numpy as np
    t = np.arange(int(48000 * secs)) / 48000
    pcm = (0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(pcm.tobytes())


def test_playback_transmit_sends_the_file_and_unkeys_itself(env, tmp_path):
    win, radio, pump = env
    f = tmp_path / "msg.wav"
    _tone_wav(f)
    assert win.load_play_file(str(f)) and "msg.wav" in win.play_name.text()
    assert not win.play_btn.isEnabled()                            # transmit controls are not enabled yet
    win.play_file(confirm=False)
    assert not win._ptt_on and radio.tx_audio_frames == 0          # refused: nothing on air
    win.tx_enable.setChecked(True)
    assert win.play_btn.isEnabled()
    win.play_level.setValue(50)
    win.play_file(confirm=False)
    assert win._ptt_on and win._player is not None and win.play_stop.isEnabled() and not win.play_choose.isEnabled()
    pump(lambda: radio.trx and radio.tx_audio_frames > 5)
    pump(lambda: not win._ptt_on, timeout=6)                       # file + tail played, then it unkeys by itself
    assert win._player is None and not radio.trx
    assert 0.2 < radio.tx_audio_peak <= 0.26                       # 0.5 amplitude x 50 % level
    assert "finished" in win.statusBar().currentMessage()


def test_playback_stop_button_and_limits(env, tmp_path, monkeypatch):
    win, radio, pump = env
    f = tmp_path / "long.wav"
    _tone_wav(f, secs=3.0)
    win.load_play_file(str(f))
    win.tx_enable.setChecked(True)
    win.play_file(confirm=False)
    pump(lambda: radio.trx and radio.tx_audio_frames > 3)
    win.stop_playback()
    pump(lambda: not radio.trx)
    assert win._player is None and not win._ptt_on and win.play_btn.isEnabled()
    win.tx_limit.setValue(5)
    short = tmp_path / "short.wav"
    _tone_wav(short, secs=0.2)
    assert win.load_play_file(str(short))
    win.tx_limit.setMinimum(1)
    win.tx_limit.setValue(1)
    long2 = tmp_path / "long2.wav"
    _tone_wav(long2, secs=1.5)
    win.load_play_file(str(long2))
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))   # modal: would block
    win.play_file(confirm=False)
    assert shown and "limit" in shown[0] and not win._ptt_on                    # longer than the auto-unkey limit
