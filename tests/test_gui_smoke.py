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
    assert not win.status_strip.isHidden()
    assert win.cw_box.isHidden()                                       # LSB: CW box hidden even with text
    win.w.send("modulation", 0, "cw")
    pump(lambda: not win.cw_box.isHidden())                            # CW mode: shown
    win.w.send("modulation", 0, "usb")
    pump(lambda: win.cw_box.isHidden())
    win.w.send("modulation", 0, "cw")
    pump(lambda: not win.cw_box.isHidden())
    assert "CQ CQ DE" in win.cw_view.toPlainText()
    assert win.cw_view.height() == 54
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
    pump(lambda: any(m.startswith("pair 123456") for m in panel.log))
    assert panel.log.index("pair?") < [i for i, m in enumerate(panel.log) if m.startswith("pair 123456")][-1]
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
    pump(lambda: win.drive.value() == 60 and win.drive_lbl.text() == "60")   # the radio's echo does not undo it
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
