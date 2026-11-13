"""Main window: connection bar, VFO, S-meter, mode/band/filter, audio and guarded TX controls."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from .. import __version__
from .audio import AVAILABLE as AUDIO_OK, MicSource, RxAudio
from .settings import (load_band_memory, load_radios, load_show_spectrum, panel_url_for,
                       parse_target, remember_radio, save_band_memory, save_show_spectrum)
from .spectrum_view import SpectrumView
from .widgets import FrequencyDisplay, SMeter
from .worker import TciWorker

# name, lo Hz, hi Hz, default Hz, default mode
BANDS = [
    ("160", 1_800_000, 2_000_000, 1_840_000, "lsb"), ("80", 3_500_000, 4_000_000, 3_700_000, "lsb"),
    ("60", 5_250_000, 5_450_000, 5_357_000, "usb"), ("40", 7_000_000, 7_300_000, 7_100_000, "lsb"),
    ("30", 10_100_000, 10_150_000, 10_130_000, "usb"), ("20", 14_000_000, 14_350_000, 14_200_000, "usb"),
    ("17", 18_068_000, 18_168_000, 18_130_000, "usb"), ("15", 21_000_000, 21_450_000, 21_250_000, "usb"),
    ("12", 24_890_000, 24_990_000, 24_950_000, "usb"), ("10", 28_000_000, 29_700_000, 28_400_000, "usb"),
    ("6", 50_000_000, 54_000_000, 50_150_000, "usb"),
]
MODE_LABELS = {"lsb": "LSB", "usb": "USB", "cw": "CW", "cwr": "CWR", "am": "AM", "nfm": "FM",
               "digl": "DIGL", "digu": "DIGU", "dsb": "DSB", "wfm": "WFM"}
STEPS = [("1 Hz", 1), ("10 Hz", 10), ("100 Hz", 100), ("500 Hz", 500), ("1 kHz", 1000),
         ("5 kHz", 5000), ("9 kHz", 9000), ("10 kHz", 10000), ("100 kHz", 100000)]
AGC_MODES = ["off", "long", "slow", "normal", "fast"]
CW_PITCH = 700

STYLE = """
QWidget { background:#0b1220; color:#dbe4f3; font-size:13px; }
QGroupBox { border:1px solid #22324f; border-radius:8px; margin-top:12px; padding-top:8px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:#8ea0bd; }
QPushButton { background:#1b2a44; border:1px solid #2a3a58; border-radius:6px; padding:6px 10px; }
QPushButton:hover { background:#24365a; }
QPushButton:checked { background:#f0a830; color:#1a1204; border-color:#f0a830; font-weight:600; }
QPushButton:disabled { color:#55637d; background:#121c30; }
QPushButton#ptt { background:#5a1f1f; border-color:#8a2d2d; font-weight:700; padding:12px; }
QPushButton#ptt:pressed { background:#d42f2f; }
QPushButton#ptt:disabled { background:#241618; border-color:#3a2326; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
  background:#0e1626; border:1px solid #2a3a58; border-radius:6px; padding:4px 6px; }
QLabel#tx_banner { background:#d42f2f; color:white; font-weight:700; padding:4px; border-radius:6px; }
QFrame#tx_group { border:1px solid #5a2d2d; border-radius:8px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #3a4c6e; border-radius:4px; background:#0e1626; }
QCheckBox::indicator:checked { background:#f0a830; border-color:#f0a830; }
QCheckBox::indicator:disabled { border-color:#2a3350; background:#0b1220; }
QSlider::groove:horizontal { height:6px; background:#22324f; border-radius:3px; }
QSlider::handle:horizontal { background:#f0a830; width:14px; margin:-5px 0; border-radius:7px; }
"""


def _btn(text: str, checkable: bool = False, slot=None) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if slot:
        (b.toggled if checkable else b.clicked).connect(slot)
    return b


class MainWindow(QMainWindow):
    def __init__(self, worker: TciWorker | None = None) -> None:
        super().__init__()
        self.setWindowTitle("X6100 TCI Remote")
        self.setStyleSheet(STYLE)
        self.w = worker or TciWorker()
        self.rx = RxAudio()
        self.mic = MicSource()
        self.band_mem = load_band_memory()
        self._freq_target: int | None = None
        self._tx_since = 0.0
        self._mode_buttons: dict[str, QPushButton] = {}
        self._ptt_on = False
        self._panel_url: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        # connection bar ------------------------------------------------------
        bar = QHBoxLayout()
        self.addr = QComboBox()
        self.addr.setEditable(True)
        self.addr.setMinimumWidth(240)
        self.addr.addItems(load_radios())
        self.addr.lineEdit().setPlaceholderText("radio address, e.g. 192.168.0.150")
        self.addr.lineEdit().returnPressed.connect(self.toggle_connection)
        self.connect_btn = _btn("Connect", slot=self.toggle_connection)
        self.status = QLabel("Not connected")
        bar.addWidget(QLabel("Radio"))
        bar.addWidget(self.addr, 1)
        bar.addWidget(self.connect_btn)
        bar.addWidget(self.status, 2)
        v.addLayout(bar)

        # VFO + meter -----------------------------------------------------------
        self.freq = FrequencyDisplay()
        self.freq.tune.connect(self.tune_by)
        self.freq.entered.connect(self.type_frequency)
        v.addWidget(self.freq)
        info = QHBoxLayout()
        self.info = QLabel("")
        self.info.setStyleSheet("color:#8ea0bd")
        info.addWidget(self.info)
        info.addStretch(1)
        self.step = QComboBox()
        for name, hz in STEPS:
            self.step.addItem(name, hz)
        self.step.setCurrentIndex(3)
        info.addWidget(QLabel("Step"))
        info.addWidget(self.step)
        info.addWidget(_btn("◀ −", slot=lambda: self.tune_by(-self.step.currentData())))
        info.addWidget(_btn("+ ▶", slot=lambda: self.tune_by(self.step.currentData())))
        v.addLayout(info)
        self.status_strip = QLabel("")
        self.status_strip.setTextFormat(Qt.TextFormat.RichText)
        self.status_strip.setToolTip("Radio status as reported by the radio's panel server (read-only)")
        self.status_strip.hide()
        v.addWidget(self.status_strip)
        self.spectrum = SpectrumView()
        self.spectrum.tune_to.connect(self.tune_to)
        self.spectrum.step.connect(lambda d: self.tune_by(d * self.step.currentData()))
        v.addWidget(self.spectrum, 1)
        self.cw_box = QGroupBox("CW decoder (decoded by the radio)")
        cwl = QHBoxLayout(self.cw_box)
        self.cw_view = QPlainTextEdit()
        self.cw_view.setReadOnly(True)
        self.cw_view.setFixedHeight(88)          # 4 lines
        self.cw_view.setMaximumBlockCount(500)
        self.cw_view.setStyleSheet("font-family:monospace; font-size:14px; color:#f0a830;")
        cwl.addWidget(self.cw_view, 1)
        cwl.addWidget(_btn("Clear", slot=self.cw_view.clear))
        self.cw_box.hide()
        v.addWidget(self.cw_box)
        self.smeter = SMeter()
        v.addWidget(self.smeter)

        # bands / modes -----------------------------------------------------------
        bands = QGroupBox("Band")
        bl = QHBoxLayout(bands)
        self._band_buttons: dict[str, QPushButton] = {}
        for name, *_ in BANDS:
            b = _btn(name + "m", True)
            b.clicked.connect(lambda _=False, n=name: self.pick_band(n))
            self._band_buttons[name] = b
            bl.addWidget(b)
        v.addWidget(bands)
        self.modes_box = QGroupBox("Mode")
        self.modes_l = QHBoxLayout(self.modes_box)
        v.addWidget(self.modes_box)

        # filter / agc / rit -------------------------------------------------------
        rx = QGroupBox("Receiver")
        g = QGridLayout(rx)
        self.filter_l = QHBoxLayout()
        g.addWidget(QLabel("Filter"), 0, 0)
        g.addLayout(self.filter_l, 0, 1, 1, 5)
        self.filter_lbl = QLabel("")
        g.addWidget(self.filter_lbl, 0, 6)
        self.agc = QComboBox()
        self.agc.addItems(AGC_MODES)
        self.agc.activated.connect(lambda i: self.w.send("agc_mode", 0, self.agc.itemText(i)))
        g.addWidget(QLabel("AGC"), 1, 0)
        g.addWidget(self.agc, 1, 1)
        self.rit = QCheckBox("RIT")
        self.rit.clicked.connect(lambda on: self.w.send("rit_enable", 0, on))
        self.rit_off = QSpinBox()
        self.rit_off.setRange(-9999, 9999)
        self.rit_off.setSingleStep(10)
        self.rit_off.setSuffix(" Hz")
        self.rit_off.editingFinished.connect(lambda: self.w.send("rit_offset", 0, self.rit_off.value()))
        self.split = QCheckBox("Split")
        self.split.clicked.connect(lambda on: self.w.send("split_enable", 0, on))
        self.lock = QCheckBox("Lock")
        self.lock.clicked.connect(lambda on: self.w.send("lock", 0, on))
        g.addWidget(self.rit, 1, 2)
        g.addWidget(self.rit_off, 1, 3)
        g.addWidget(self.split, 1, 4)
        g.addWidget(self.lock, 1, 5)
        v.addWidget(rx)

        # audio -------------------------------------------------------------------
        au = QGroupBox("Audio")
        al = QHBoxLayout(au)
        self.sound = _btn("Sound", True, self.toggle_sound)
        self.sound.setEnabled(AUDIO_OK)
        if not AUDIO_OK:
            self.sound.setToolTip("Qt Multimedia is not installed (pip install PySide6)")
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.valueChanged.connect(lambda x: self.rx.set_volume(x / 100))
        self.mute = _btn("Mute", True, self.rx.set_muted)
        al.addWidget(self.sound)
        al.addWidget(QLabel("Volume"))
        al.addWidget(self.vol, 1)
        al.addWidget(self.mute)
        v.addWidget(au)

        # transmit (guarded) ---------------------------------------------------------
        self.tx_box = QFrame()
        self.tx_box.setObjectName("tx_group")
        tl = QGridLayout(self.tx_box)
        self.tx_enable = QCheckBox("Enable transmit controls (you are responsible for what goes on air)")
        self.tx_enable.toggled.connect(self.tx_enable_changed)
        tl.addWidget(self.tx_enable, 0, 0, 1, 4)
        self.ptt = QPushButton("PTT  (hold)")
        self.ptt.setObjectName("ptt")
        self.ptt.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ptt.pressed.connect(lambda: self.set_ptt(True))
        self.ptt.released.connect(lambda: self.set_ptt(False))
        tl.addWidget(self.ptt, 1, 0, 1, 2)
        self.pc_mic = QCheckBox("Use this computer's microphone (experimental)")
        self.pc_mic.setEnabled(AUDIO_OK)
        tl.addWidget(self.pc_mic, 1, 2, 1, 2)
        tl.addWidget(QLabel("Drive"), 2, 0)
        self.drive = QSlider(Qt.Orientation.Horizontal)
        self.drive.setRange(0, 100)
        self.drive.sliderReleased.connect(lambda: self.w.send("drive", 0, self.drive.value()))
        self.drive_lbl = QLabel("-")
        tl.addWidget(self.drive, 2, 1, 1, 2)
        tl.addWidget(self.drive_lbl, 2, 3)
        tl.addWidget(QLabel("Auto-unkey after"), 3, 0)
        self.tx_limit = QSpinBox()
        self.tx_limit.setRange(5, 600)
        self.tx_limit.setValue(120)
        self.tx_limit.setSuffix(" s")
        tl.addWidget(self.tx_limit, 3, 1)
        self.tx_banner = QLabel("● TRANSMITTING")
        self.tx_banner.setObjectName("tx_banner")
        self.tx_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tx_banner.hide()
        tl.addWidget(self.tx_banner, 3, 2, 1, 2)
        v.addWidget(self.tx_box)
        self.tx_enable_changed(False)

        # protocol log dock -----------------------------------------------------------
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.dock = QDockWidget("Protocol log", self)
        self.dock.setWidget(self.log)
        self.dock.hide()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        m = self.menuBar().addMenu("&View")
        self.spectrum_act = QAction("Spectrum && waterfall", self)
        self.spectrum_act.setCheckable(True)
        self.spectrum_act.setChecked(load_show_spectrum())
        self.spectrum_act.toggled.connect(self.toggle_spectrum)
        m.addAction(self.spectrum_act)
        act = self.dock.toggleViewAction()
        act.setText("Protocol log")
        m.addAction(act)
        self.spots_act = QAction("DX spots on spectrum", self)
        self.spots_act.setCheckable(True)
        self.spots_act.setChecked(True)
        self.spots_act.toggled.connect(self.spectrum.set_show_spots)
        m.addAction(self.spots_act)
        self.spectrum.setVisible(self.spectrum_act.isChecked())
        h = self.menuBar().addMenu("&Help")
        about = QAction("About", self)
        about.triggered.connect(lambda: self.statusBar().showMessage(
            "X6100 TCI Remote %s - MIT licensed, talks Expert Electronics TCI" % __version__, 6000))
        h.addAction(about)

        # watchdog + wiring -------------------------------------------------------------
        self.tx_timer = QTimer(self)
        self.tx_timer.setInterval(250)
        self.tx_timer.timeout.connect(self._tx_watchdog)
        self.target_timer = QTimer(self)
        self.target_timer.setSingleShot(True)
        self.target_timer.timeout.connect(self._clear_target)
        self.w.status.connect(self.on_status)
        self.w.changed.connect(self.refresh)
        self.w.audio.connect(self.rx.push)
        self.w.spectrum.connect(self.spectrum.push)
        self.w.panel_status.connect(self.on_panel_status)
        self.w.panel_info.connect(self.on_panel_info)
        self.w.raw.connect(lambda s: self.log.appendPlainText(s) if self.dock.isVisible() else None)
        self.resize(760, 1040)

    # state -> widgets ----------------------------------------------------------------
    @property
    def state(self):
        return self.w.state

    def refresh(self, what: str = "") -> None:
        st = self.state
        if what in ("", "vfo"):
            hz = self._freq_target if self._freq_target is not None else st.freq
            self.freq.set_freq(hz)
            self._update_band(st.freq)
            if self._freq_target == st.freq:
                self._freq_target = None
        if what in ("", "lock"):
            self.freq.locked = st.lock
            self.lock.setChecked(st.lock)
            self.freq.update()
        if what in ("", "smeter"):
            self.smeter.set_dbm(st.smeter_dbm)
        if what in ("", "modulations_list", "ready") or not self._mode_buttons:
            self._build_modes()
        if what in ("", "mode", "filter", "ready"):
            for m, b in self._mode_buttons.items():
                b.setChecked(m == st.mode)
            self._build_filters()
            bw = abs(st.filter_hi - st.filter_lo)
            self.filter_lbl.setText("%d…%d Hz  (%.1f kHz)" % (st.filter_lo, st.filter_hi, bw / 1000))
            self.spectrum.set_passband(st.filter_lo, st.filter_hi)
            self._update_cw_visibility()
        if what in ("", "agc"):
            self.agc.setCurrentText(st.agc)
        if what in ("", "rit_enable", "rit_offset"):
            self.rit.setChecked(st.rit_enable)
            self.rit_off.setValue(st.rit_offset)
        if what in ("", "split_enable"):
            self.split.setChecked(st.split)
        if what in ("", "drive") and not self.drive.isSliderDown():
            self.drive.setValue(st.drive)
            self.drive_lbl.setText(str(st.drive))
        if what in ("", "trx"):
            self.tx_banner.setVisible(st.trx)
        if what in ("", "device", "protocol", "ready"):
            self.info.setText("%s  %s" % (st.device, st.protocol))

    def _build_modes(self) -> None:
        names = self.state.modulations or ["lsb", "usb", "cw", "am", "nfm"]
        if list(self._mode_buttons) == names:
            return
        while self.modes_l.count():
            w = self.modes_l.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._mode_buttons = {}
        for m in names:
            b = _btn(MODE_LABELS.get(m, m.upper()), True)
            b.clicked.connect(lambda _=False, mm=m: self.w.send("modulation", 0, mm))
            self._mode_buttons[m] = b
            self.modes_l.addWidget(b)

    def _filter_presets(self, mode: str) -> list[tuple[str, int, int]]:
        if mode == "lsb" or mode == "digl":
            return [("%.1fk" % (w / 1000), -(w + 50), -50) for w in (1800, 2400, 2700, 3000)]
        if mode in ("usb", "digu"):
            return [("%.1fk" % (w / 1000), 50, w + 50) for w in (1800, 2400, 2700, 3000)]
        if mode in ("cw", "cwr"):
            return [(str(w), CW_PITCH - w // 2, CW_PITCH + w // 2) for w in (200, 500, 1000, 2000)]
        return [("%gk" % (w / 1000), -w // 2, w // 2) for w in (4000, 6000, 9000, 12000)]

    def _build_filters(self) -> None:
        mode = self.state.mode
        key = (mode, self.state.filter_lo, self.state.filter_hi)
        if getattr(self, "_filter_key", None) == key:
            return
        self._filter_key = key
        while self.filter_l.count():
            w = self.filter_l.takeAt(0).widget()
            if w:
                w.deleteLater()
        for text, lo, hi in self._filter_presets(mode):
            b = _btn(text, True)
            b.setChecked((lo, hi) == (self.state.filter_lo, self.state.filter_hi))
            b.clicked.connect(lambda _=False, a=lo, c=hi: self.w.send("rx_filter_band", 0, a, c))
            self.filter_l.addWidget(b)
        self.filter_l.addStretch(1)

    # tuning ----------------------------------------------------------------------------
    def _band_of(self, hz: int):
        return next((b for b in BANDS if b[1] <= hz <= b[2]), None)

    def _update_band(self, hz: int) -> None:
        band = self._band_of(hz)
        for name, b in self._band_buttons.items():
            b.setChecked(band is not None and band[0] == name)
        if band is not None and self.state.mode:
            self.band_mem[band[0]] = [hz, self.state.mode]

    def tune_by(self, delta: int) -> None:
        if self.state.lock or not self.w.client:
            return
        lo, hi = self.state.vfo_limits
        base = self._freq_target if self._freq_target is not None else self.state.freq
        new = base + int(delta)
        if hi:
            new = max(lo, min(hi, new))
        self._freq_target = new
        self.freq.set_freq(new)
        self.w.send("vfo", 0, 0, new)
        self.target_timer.start(700)

    def tune_to(self, hz: int) -> None:
        """Tune to an absolute frequency (clicked in the spectrum)."""
        base = self._freq_target if self._freq_target is not None else self.state.freq
        self.tune_by(hz - base)

    def toggle_spectrum(self, on: bool) -> None:
        save_show_spectrum(on)
        self.spectrum.setVisible(on)
        if not on:
            self.w.disconnect_panel()
        elif self._panel_url and self.connect_btn.text() == "Disconnect":
            self.w.connect_panel(self._panel_url)

    def _clear_target(self) -> None:
        self._freq_target = None
        self.refresh("vfo")

    def type_frequency(self) -> None:
        text, ok = QInputDialog.getText(self, "Set frequency", "Frequency (MHz, e.g. 14.074):",
                                        text="%.6f" % (self.state.freq / 1e6))
        if ok and text.strip():
            try:
                hz = int(round(float(text.replace(",", ".").replace(" ", "")) * 1e6))
            except ValueError:
                self.statusBar().showMessage("Not a frequency: %s" % text, 4000)
                return
            self._freq_target = hz
            self.w.send("vfo", 0, 0, hz)
            self.target_timer.start(700)

    def pick_band(self, name: str) -> None:
        band = next(b for b in BANDS if b[0] == name)
        hz, mode = self.band_mem.get(name, [band[3], band[4]])
        self.w.send("modulation", 0, mode)
        self.w.send("vfo", 0, 0, hz)

    # audio ------------------------------------------------------------------------------
    def toggle_sound(self, on: bool) -> None:
        if on:
            if not self.rx.start(self.state.audio_sample_rate or 48000):
                self.sound.setChecked(False)
                self.statusBar().showMessage("No audio output available", 5000)
                return
            self.w.set_audio(True)
        else:
            self.w.set_audio(False)
            self.rx.stop()

    # transmit ---------------------------------------------------------------------------
    def tx_enable_changed(self, on: bool) -> None:
        for wdg in (self.ptt, self.drive, self.tx_limit):
            wdg.setEnabled(on)
        self.pc_mic.setEnabled(on and AUDIO_OK)
        if not on and self._ptt_on:
            self.set_ptt(False)

    def set_ptt(self, on: bool) -> None:
        if on and (not self.tx_enable.isChecked() or not self.w.client):
            return
        if on == self._ptt_on:
            return
        self._ptt_on = on
        use_pc_mic = self.pc_mic.isChecked() and on
        if on and use_pc_mic:
            if not self.mic.start():
                self.statusBar().showMessage("Microphone unavailable", 5000)
                self._ptt_on = False
                return
            self.w.set_tx_source(self.mic.read_frames)
        self.w.set_ptt(on, use_pc_mic)
        if on:
            self._tx_since = time.monotonic()
            self.tx_timer.start()
        else:
            self.tx_timer.stop()
            self.mic.stop()
            self.w.set_tx_source(None)
        self.ptt.setDown(on) if not self.ptt.isDown() else None

    def _tx_watchdog(self) -> None:
        if self._ptt_on and time.monotonic() - self._tx_since > self.tx_limit.value():
            self.set_ptt(False)
            self.statusBar().showMessage("Auto-unkeyed: transmit time limit reached", 8000)

    # keyboard / focus -----------------------------------------------------------------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        k, big = e.key(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        mult = 10 if big else 1
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.tune_by((1 if k == Qt.Key.Key_Right else -1) * self.step.currentData() * mult)
        elif k == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.set_ptt(True)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.set_ptt(False)
        else:
            super().keyReleaseEvent(e)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self._ptt_on:
            self.set_ptt(False)                    # never stay keyed after losing focus
        super().changeEvent(e)

    def closeEvent(self, e) -> None:
        self.set_ptt(False)
        save_band_memory(self.band_mem)
        self.rx.stop()
        self.mic.stop()
        self.w.shutdown()
        super().closeEvent(e)

    # connection ---------------------------------------------------------------------------------
    def toggle_connection(self) -> None:
        if self.connect_btn.text() == "Disconnect":
            self.w.disconnect_from()
            return
        text = self.addr.currentText().strip()
        if not text:
            self.statusBar().showMessage("Enter the radio's address first", 4000)
            return
        remember_radio(text)
        self.connect_to(parse_target(text))

    def connect_to(self, url: str, panel_url: str | None = None) -> None:
        self.connect_btn.setText("Disconnect")
        self._panel_url = panel_url or panel_url_for(url)
        self.w.connect_to(url)
        if self.spectrum_act.isChecked():
            self.spectrum.clear()
            self.spectrum.set_plan([])
            self.spectrum.set_spots([])
            self.cw_view.clear()
            self.status_strip.hide()
            self.spectrum.set_message("Waiting for spectrum...")
            self.w.connect_panel(self._panel_url)

    def on_panel_info(self, kind: str) -> None:
        info = self.w.info
        if kind == "plan":
            self.spectrum.set_plan(info.plan)
        elif kind == "spots":
            self.spectrum.set_spots(info.spots)
        elif kind in ("state", "ft8"):
            self._update_status_strip()
        elif kind == "cw":
            self.cw_view.setPlainText(info.cw_text)
            self.cw_view.verticalScrollBar().setValue(self.cw_view.verticalScrollBar().maximum())
            self._update_cw_visibility()

    def _update_status_strip(self) -> None:
        info = self.w.info
        parts = []
        for label, value, on in info.status_items():
            color = "#f0a830" if on else "#55637d"
            parts.append("<span style='color:#8ea0bd'>%s</span> <span style='color:%s'>%s</span>"
                         % (label, color, value))
        ft8 = info.ft8
        if ft8.get("open"):
            tag = "TX" if ft8.get("tx") else "RX"
            parts.append("<span style='color:#3ddc97'>FT8 app open (%s)</span>" % tag)
        self.status_strip.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))
        self.status_strip.setVisible(bool(parts))

    def _update_cw_visibility(self) -> None:
        self.cw_box.setVisible(self.state.mode in ("cw", "cwr"))

    def on_panel_status(self, state: str, detail: str) -> None:
        if state == "connected":
            self.spectrum.set_message("Waiting for spectrum...")
        elif state == "connecting":
            self.spectrum.set_message("Connecting to the spectrum feed...")
        else:
            self.spectrum.set_message(("No spectrum - " + detail).strip(" -") if detail else "No spectrum")

    def on_status(self, state: str, detail: str) -> None:
        colors = {"connected": "#3ddc97", "connecting": "#f0a830", "disconnected": "#ff8a8a"}
        text = {"connected": "Connected", "connecting": "Connecting to " + detail,
                "disconnected": ("Disconnected " + detail).strip()}[state]
        self.status.setText("<span style='color:%s'>●</span> %s" % (colors[state], text))
        if state == "disconnected" and not detail:
            self.connect_btn.setText("Connect")
        if state == "connected":
            self.refresh("")
