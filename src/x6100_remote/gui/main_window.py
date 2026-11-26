"""Main window: connection bar, VFO, S-meter, mode/band/filter, audio and guarded TX controls."""
from __future__ import annotations

import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDockWidget,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QKeySequenceEdit, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..audiofile import (MAX_REC_S, FilePlayer, WavRecorder, default_rec_dir, read_audio, recording_name,
                         unique_path)
from ..automode import desired_mode, needs_change
from ..cwtuner import target_hz
from ..ipc import CommandServer
from .audio import AVAILABLE as AUDIO_OK, MicSource, RxAudio
from .settings import (load_band_memory, load_choice, load_flag, load_panel_token, load_radios, load_show_spectrum,
                       load_window_geometry, panel_url_for, parse_target, remember_radio, save_band_memory,
                       save_choice, save_flag, save_panel_token, save_show_spectrum, save_window_geometry)
from .spectrum_view import (DEFAULT_SPECTRUM, DEFAULT_SPOTS, DEFAULT_WATERFALL, SPECTRUM_SCHEMES, SPOT_SCHEMES,
                            WATERFALL_SCHEMES, ZOOM_LEVELS, SpectrumView)
from .themes import DEFAULT_THEME, THEMES, build_style
from .widgets import FrequencyDisplay, SMeter, TxMeterPopup, apply_palette
from .worker import TciWorker

# name, lo Hz, hi Hz, default Hz, default mode
BANDS = [
    ("160", 1_800_000, 2_000_000, 1_840_000, "lsb"), ("80", 3_500_000, 4_000_000, 3_700_000, "lsb"),
    ("60", 5_250_000, 5_450_000, 5_357_000, "lsb"), ("40", 7_000_000, 7_300_000, 7_100_000, "lsb"),
    ("30", 10_100_000, 10_150_000, 10_130_000, "usb"), ("20", 14_000_000, 14_350_000, 14_200_000, "usb"),
    ("17", 18_068_000, 18_168_000, 18_130_000, "usb"), ("15", 21_000_000, 21_450_000, 21_250_000, "usb"),
    ("12", 24_890_000, 24_990_000, 24_950_000, "usb"), ("10", 28_000_000, 29_700_000, 28_400_000, "usb"),
    ("6", 50_000_000, 54_000_000, 50_150_000, "usb"),
]
MODE_LABELS = {"lsb": "LSB", "usb": "USB", "cw": "CW", "cwr": "CWR", "am": "AM", "nfm": "FM",
               "digl": "DIGL", "digu": "DIGU", "dsb": "DSB", "wfm": "WFM"}
STEPS = [("1 Hz", 1), ("10 Hz", 10), ("100 Hz", 100), ("500 Hz", 500), ("1 kHz", 1000),
         ("5 kHz", 5000), ("9 kHz", 9000), ("10 kHz", 10000), ("100 kHz", 100000)]
DOUBLE_SIDEBAND_MODES = ("am", "dsb", "nfm", "wfm")      # passband is symmetric around the carrier
AGC_MODES = ["off", "long", "slow", "normal", "fast"]
CW_PITCH = 700


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
        self._panel_up = False
        self.theme_name = load_choice("theme", DEFAULT_THEME)
        if self.theme_name not in THEMES:
            self.theme_name = DEFAULT_THEME
        apply_palette(THEMES[self.theme_name])
        self.setStyleSheet(build_style(THEMES[self.theme_name]))
        self.w = worker or TciWorker()
        self.rx = RxAudio()
        self.mic = MicSource()
        self.band_mem = load_band_memory()
        self._freq_target: int | None = None
        self._tx_since = 0.0
        self._mode_buttons: dict[str, QPushButton] = {}
        self._ptt_on = False
        self._ptt_external = False         # keyed by an OS hotkey (--ptt): does not unkey when the window loses focus
        self.cmd_server: CommandServer | None = None
        self._panel_url: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        self.tx_meter = TxMeterPopup(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(500)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start()

        # connection widgets live in Settings > Connection; the status is in the status bar at the bottom ---------
        self.addr = QComboBox()
        self.addr.setEditable(True)
        self.addr.setMinimumWidth(240)
        self.addr.addItems(load_radios())
        self.addr.lineEdit().setPlaceholderText("radio address, e.g. 192.168.0.150")
        self.addr.lineEdit().returnPressed.connect(self.toggle_connection)
        self.connect_btn = _btn("Connect", slot=self.toggle_connection)
        self.status = QLabel("Not connected")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.statusBar().addPermanentWidget(self.status)
        self._space_ptt = False              # the PTT key is held and keying
        self._recording = False                  # REC is on (the file opens with the first audio block)
        self._rec: WavRecorder | None = None
        self._rec_started_audio = False          # REC switched the radio's audio stream on (Sound was off)
        self._rec_shown = -1
        self._play_samples: tuple | None = None  # (samples, rate) of the file chosen for playback-transmit
        self._play_path: Path | None = None
        self._player: FilePlayer | None = None
        self._auto_mode_on = load_flag("auto_mode", True)
        self._auto_key: tuple | None = None      # (band, wanted mode) of the last place we looked at
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(60)
        self._release_timer.timeout.connect(self._ptt_key_released)
        self._ptt_key_on = load_flag("ptt_key", True)
        self._ptt_key = self._key_from_text(load_choice("ptt_key", "Space"))
        self._build_settings_dialog()

        # VFO + meter -----------------------------------------------------------
        self.freq = FrequencyDisplay()
        self.freq.tune.connect(self.tune_by)
        self.freq.entered.connect(self.type_frequency)
        # the UTC clock sits in its own box to the right of the frequency
        self.clock_box = QFrame()
        self.clock_box.setObjectName("clock_box")
        cbl = QVBoxLayout(self.clock_box)
        cbl.setContentsMargins(14, 4, 14, 4)
        cbl.setSpacing(0)
        self.clock = QLabel("")
        cf = QFont(self.font())
        cf.setFamilies(["DejaVu Sans Mono", "Liberation Mono", "Consolas", "Menlo", "Courier New", "monospace"])
        cf.setStyleHint(QFont.StyleHint.Monospace)
        cf.setPointSize(24)
        cf.setWeight(QFont.Weight.DemiBold)
        self.clock.setFont(cf)
        self.clock.setObjectName("clock")          # coloured like the frequency digits by the theme
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.utc_lbl = QLabel("UTC")
        self.utc_lbl.setObjectName("utc_lbl")
        self.utc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cbl.addStretch(1)
        cbl.addWidget(self.clock)
        cbl.addWidget(self.utc_lbl)
        cbl.addStretch(1)
        self.clock_box.setToolTip("Coordinated Universal Time (UTC)")
        vfo_row = QHBoxLayout()
        vfo_row.setSpacing(10)
        vfo_row.addWidget(self.freq, 1)
        vfo_row.addWidget(self.clock_box)
        v.addLayout(vfo_row)
        self._tick_clock()
        info = QHBoxLayout()
        self.info = QLabel("")
        self.info.setObjectName("info")
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
        self.zoom = QComboBox()
        self.zoom.setToolTip("Spectrum and waterfall zoom (display only; the radio's own span is not changed)")
        for z in ZOOM_LEVELS:
            self.zoom.addItem("%dx" % z, z)
        info.addSpacing(12)
        info.addWidget(QLabel("Zoom"))
        info.addWidget(self.zoom)
        info.addSpacing(12)
        self.fullscreen_btn = _btn("⛶ Full screen", slot=self.toggle_fullscreen)
        self.fullscreen_btn.setToolTip("Full screen without window borders (F11; Esc to leave)")
        info.addWidget(self.fullscreen_btn)
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
        self.spectrum.set_zoom(self.zoom.currentData())
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        self.spectrum.set_waterfall_scheme(self.wf_scheme())
        self.spectrum.set_spectrum_scheme(self.sp_scheme())
        self.spectrum.set_noise_floor(*self.noise_floor_settings())
        self.spectrum.set_trace_floor(*self.trace_floor_settings())
        self.spectrum.set_spot_scheme(self.spot_scheme())
        self.cw_box = QGroupBox("CW decoder (decoded by the radio)")
        cwl = QHBoxLayout(self.cw_box)
        cwl.setContentsMargins(8, 2, 8, 4)
        self.cw_view = QPlainTextEdit()
        self.cw_view.setReadOnly(True)
        self.cw_view.setFixedHeight(78)          # 3 lines
        self.cw_view.setMaximumBlockCount(500)
        self.cw_view.setObjectName("cw_view")
        cwl.addWidget(self.cw_view, 1)
        cwl.addWidget(_btn("Clear", slot=self.clear_cw))
        self.cw_box.hide()
        v.addWidget(self.cw_box)
        self.smeter = SMeter()
        v.addWidget(self.smeter)

        # bands / modes -----------------------------------------------------------
        bands = self.band_box = QGroupBox("Band")
        bl = QHBoxLayout(bands)
        bl.setContentsMargins(8, 2, 8, 4)
        bl.setSpacing(3)
        self._band_buttons: dict[str, QPushButton] = {}
        for name, *_ in BANDS:
            b = _btn(name + "m", True)
            b.clicked.connect(lambda _=False, n=name: self.pick_band(n))
            self._band_buttons[name] = b
            bl.addWidget(b)
        v.addWidget(bands)
        self.modes_box = QGroupBox("Mode")
        self.modes_l = QHBoxLayout(self.modes_box)
        self.modes_l.setContentsMargins(8, 2, 8, 4)
        self.modes_l.setSpacing(3)
        v.addWidget(self.modes_box)

        # filter / agc / rit -------------------------------------------------------
        rx = self.rx_box = QGroupBox("Receiver")
        g = QGridLayout(rx)
        g.setContentsMargins(8, 2, 8, 4)
        g.setVerticalSpacing(4)
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
        # radio keys (pressed over the panel socket; PRE and ATU state comes back from the radio) -------------
        keys_l = QHBoxLayout()
        keys_l.addWidget(QLabel("Keys"))
        self._key_buttons: dict[str, QPushButton] = {}
        for key, label, tip in (("PRE", "PRE", "Preamp key (cycles the radio's preamp setting)"),
                                ("AB", "A/B", "Swap VFO A and B"), ("VM", "V/M", "VFO / memory"),
                                ("FST", "FST", "Fast tuning")):
            b = _btn(label, slot=lambda _=False, k=key: self.press_key(k))
            b.setToolTip(tip)
            self._key_buttons[key] = b
            keys_l.addWidget(b)
        atu = _btn("ATU", slot=lambda: self.press_key("ATU"))
        atu.setToolTip("Antenna tuner on/off")
        self._key_buttons["ATU"] = atu
        keys_l.addWidget(atu)
        self.atu_tune = _btn("Tune ATU", slot=self.tune_atu)
        self.atu_tune.setToolTip("Starts an antenna-tuner cycle: the radio TRANSMITS a carrier while it tunes. "
                                 "Needs 'Enable transmit controls'.")
        keys_l.addWidget(self.atu_tune)
        self.pair_btn = _btn("Pair...", slot=self.pair_panel)
        self.pair_btn.setToolTip("These keys need this app to be paired with the radio (6-digit code)")
        keys_l.addWidget(self.pair_btn)
        keys_l.addStretch(1)
        g.addLayout(keys_l, 2, 0, 1, 7)
        v.addWidget(rx)

        # audio -------------------------------------------------------------------
        au = self.audio_box = QGroupBox("Audio")
        al = QHBoxLayout(au)
        al.setContentsMargins(8, 2, 8, 4)
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

        # recorder / playback-transmit ------------------------------------------------
        rb = self.rec_box = QGroupBox("Recorder / playback")
        rv = QVBoxLayout(rb)
        rv.setContentsMargins(8, 2, 8, 4)
        r1 = QHBoxLayout()
        self.rec_btn = _btn("\u25cf Rec", True, self.toggle_record)
        self.rec_btn.setStyleSheet("QPushButton:checked { background:#b32323; border-color:#ff5a5a; color:white; }")
        self.rec_btn.setToolTip("Record the radio's receive audio to a WAV file (48 kHz, 16 bit, stereo). The file "
                                "name has the UTC time, frequency and mode.")
        self.rec_time = QLabel("00:00")
        self.rec_time.setMinimumWidth(48)
        self.rec_info = QLabel("")
        self.rec_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        r1.addWidget(self.rec_btn)
        r1.addWidget(self.rec_time)
        r1.addWidget(self.rec_info, 1)
        r1.addWidget(_btn("Folder", slot=self.open_rec_folder))
        rv.addLayout(r1)
        r2 = QHBoxLayout()
        self.play_choose = _btn("File...", slot=self.choose_play_file)
        self.play_name = QLabel("No file selected")
        self.play_level = QSlider(Qt.Orientation.Horizontal)
        self.play_level.setRange(5, 100)
        self.play_level.setValue(60)
        self.play_level.setMaximumWidth(120)
        self.play_level.setToolTip("Audio level sent to the radio (watch ALC in the TX meter; it can be changed while "
                                   "the file plays)")
        self.play_level_lbl = QLabel("60%")
        self.play_level.valueChanged.connect(self._play_level_changed)
        self.play_btn = _btn("\u25b6 Transmit file", slot=lambda: self.play_file())
        self.play_btn.setToolTip("Transmit the chosen WAV file. Needs 'Enable transmit controls'. Uses the radio's "
                                 "current frequency, mode and power.")
        self.play_stop = _btn("\u25a0 Stop", slot=self.stop_playback)
        r2.addWidget(self.play_choose)
        r2.addWidget(self.play_name, 1)
        r2.addWidget(QLabel("Level"))
        r2.addWidget(self.play_level)
        r2.addWidget(self.play_level_lbl)
        r2.addWidget(self.play_btn)
        r2.addWidget(self.play_stop)
        rv.addLayout(r2)
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)
        self._play_timer.timeout.connect(self._play_tick)
        v.addWidget(rb)

        # transmit (guarded) ---------------------------------------------------------
        self.tx_box = QFrame()
        self.tx_box.setObjectName("tx_group")
        tl = QGridLayout(self.tx_box)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setVerticalSpacing(4)
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
        tl.addWidget(QLabel("Power"), 2, 0)
        self.drive = QSlider(Qt.Orientation.Horizontal)
        # The radio's drive value is 0-100 and maps linearly to 0.1-10 W (measured: drive 10 = 1.1 W on the radio's
        # own display), so one step is about 0.1 W.
        self.drive.setRange(0, 100)
        self.drive.setToolTip("Transmit power, 0.1 - 10 W in steps of about 0.1 W (TCI drive 0-100)")
        self.drive_lbl = QLabel("-")
        self.drive_lbl.setMinimumWidth(52)
        # send while dragging, scrolling the wheel, using the keys or clicking the bar (not only on mouse release);
        # at most ~12 per second, and the final value is always sent
        self._drive_sent: int | None = None
        self._drive_pending = False
        self._drive_local_at = 0.0
        self._drive_timer = QTimer(self)
        self._drive_timer.setSingleShot(True)
        self._drive_timer.setInterval(80)
        self._drive_timer.timeout.connect(self._drive_tick)
        self.drive.valueChanged.connect(self._drive_changed)
        self.drive.sliderReleased.connect(self._drive_flush)
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
        m.addSeparator()
        for key, label, box in (("band", "Band", self.band_box), ("mode", "Mode", self.modes_box),
                                ("receiver", "Receiver", self.rx_box), ("audio", "Audio", self.audio_box),
                                ("recorder", "Recorder / playback", self.rec_box),
                                ("transmit", "Transmit / PTT", self.tx_box)):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(load_flag("show_" + key))
            act.toggled.connect(lambda on, k=key, b=box: self._show_group(k, b, on))
            box.setVisible(act.isChecked())
            m.addAction(act)
            setattr(self, "view_" + key + "_act", act)
        m.addSeparator()
        self.fullscreen_act = QAction("Full screen", self)
        self.fullscreen_act.setShortcut("F11")
        self.fullscreen_act.setCheckable(True)
        self.fullscreen_act.triggered.connect(self.toggle_fullscreen)
        m.addAction(self.fullscreen_act)
        self.cw_tuner_act = QAction("CW tuner indicator", self)
        self.cw_tuner_act.setCheckable(True)
        self.cw_tuner_act.setChecked(load_flag("cw_tuner"))
        self.cw_tuner_act.toggled.connect(lambda on: (save_flag("cw_tuner", on), self.spectrum.set_show_cw_tuner(on)))
        self.spectrum.set_show_cw_tuner(self.cw_tuner_act.isChecked())
        m.addAction(self.cw_tuner_act)
        self.spots_act = QAction("DX spots on spectrum", self)
        self.spots_act.setCheckable(True)
        self.spots_act.setChecked(True)
        self.spots_act.toggled.connect(self.spectrum.set_show_spots)
        m.addAction(self.spots_act)
        self.spectrum.setVisible(self.spectrum_act.isChecked())
        sm = self.menuBar().addMenu("&Settings")
        sm.addAction("Settings...", self.open_settings)
        tm = sm.addMenu("Theme")
        group = QActionGroup(self)
        for name in THEMES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(name == self.theme_name)
            act.triggered.connect(lambda _=False, n=name: self.set_theme(n))
            group.addAction(act)
            tm.addAction(act)
        h = self.menuBar().addMenu("&Help")
        about = QAction("About", self)
        about.triggered.connect(self.show_about)
        h.addAction(about)

        # watchdog + wiring -------------------------------------------------------------
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)     # Space = push-to-talk wherever the focus is in this window
        self.tx_timer = QTimer(self)
        self.tx_timer.setInterval(250)
        self.tx_timer.timeout.connect(self._tx_watchdog)
        self.target_timer = QTimer(self)
        self.target_timer.setSingleShot(True)
        self.target_timer.timeout.connect(self._clear_target)
        self.w.status.connect(self.on_status)
        self.w.changed.connect(self.refresh)
        self.w.audio.connect(self.rx.push)
        self.w.audio.connect(self._on_rx_audio)
        self.w.spectrum.connect(self.spectrum.push)
        self.w.panel_status.connect(self.on_panel_status)
        self.w.panel_info.connect(self.on_panel_info)
        self.w.panel_notice.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.w.panel_paired.connect(self.on_paired)
        self.w.raw.connect(lambda s: self.log.appendPlainText(s) if self.dock.isVisible() else None)
        self._update_key_buttons()
        geometry = load_window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            avail = self.screen().availableGeometry() if self.screen() else None
            h = min(900, avail.height() - 60) if avail else 900
            w = min(1060, avail.width() - 60) if avail else 1060
            self.resize(w, h)

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
            self._auto_mode(st.freq)
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
            if st.mode in ("cw", "cwr"):
                # the radio's CW filter is defined around the pitch; draw it centred on the VFO line, where the
                # tuned signal sits, and switch the CW tuner bars on
                self._apply_cw_tuner(st.mode, bw)
            else:
                lo, hi = st.filter_lo, st.filter_hi
                if st.mode in DOUBLE_SIDEBAND_MODES:
                    # the carrier is in the middle: the radio reports one sideband's width, so show both sides
                    lo, hi = -max(abs(lo), abs(hi)), max(abs(lo), abs(hi))
                self.spectrum.set_passband(lo, hi)
                self.spectrum.set_cw_tuner(None)
            self._update_cw_visibility()
        if what in ("", "agc"):
            self.agc.setCurrentText(st.agc)
        if what in ("", "rit_enable", "rit_offset"):
            self.rit.setChecked(st.rit_enable)
            self.rit_off.setValue(st.rit_offset)
        if what in ("", "split_enable"):
            self.split.setChecked(st.split)
        if (what in ("", "drive") and not self.drive.isSliderDown()
                and time.monotonic() - self._drive_local_at > 0.8):      # do not fight our own recent changes
            self.drive.blockSignals(True)
            self.drive.setValue(st.drive)
            self.drive.blockSignals(False)
            self._drive_sent = st.drive
            self.drive_lbl.setText(self._power_text(st.drive))
        if what in ("", "trx"):
            self.tx_banner.setVisible(st.trx)
            self.spectrum.set_transmitting(st.trx)
            if st.trx and not self.tx_meter.isVisible():
                self.tx_meter.begin()
                self.tx_meter.reposition(self.spectrum)
                self._tx_meter_update()
            elif not st.trx:
                self.tx_meter.end()
                if self._ptt_on and time.monotonic() - self._tx_since > 1.0:
                    self._space_ptt = False                  # the radio stopped transmitting on its own: show it
                    self.set_ptt(False)
                    self.statusBar().showMessage("The radio ended the transmission (release the key and press again)",
                                                 8000)
        if what in ("", "device", "protocol", "ready"):
            self.info.setText(st.device)
            self.info.setToolTip("TCI protocol: %s" % st.protocol if st.protocol else "")

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

    def _auto_mode(self, hz: int, apply: bool = True) -> None:
        """Switch the mode when the frequency moves into another band or segment (see automode.py). Only on such a
        change, so a mode picked by hand stays while tuning inside the same segment. Never while transmitting, and
        the first look after connecting only records where we are."""
        if not hz:
            return
        band = self._band_of(hz)
        wanted = desired_mode(hz, band is not None, self.w.info.plan)
        key = (band[0] if band else None, wanted)
        first = self._auto_key is None
        changed = key != self._auto_key
        self._auto_key = key
        if (not apply or first or not changed or not self._auto_mode_on or self.state.lock or self._ptt_on
                or self.state.trx or not self.w.client):
            return
        if needs_change(self.state.mode, wanted):
            self.statusBar().showMessage("Mode set to %s for this part of the band" % MODE_LABELS.get(wanted, wanted),
                                         5000)
            self.w.send("modulation", 0, wanted)

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

    @staticmethod
    def _power_text(drive: int) -> str:
        return "%.1f W" % (0.1 + 0.099 * drive)

    def _drive_changed(self, value: int) -> None:
        self.drive_lbl.setText(self._power_text(value))
        self._drive_local_at = time.monotonic()
        if self._drive_timer.isActive():
            self._drive_pending = True                    # sent when the timer fires
        else:
            self._drive_send()
            self._drive_timer.start()

    def _drive_send(self) -> None:
        v = self.drive.value()
        if v != self._drive_sent and self.w.client:
            self._drive_sent = v
            self.w.send("drive", 0, v)
        self._drive_pending = False

    def _drive_tick(self) -> None:
        if self._drive_pending:
            self._drive_send()
            self._drive_timer.start()

    def _drive_flush(self) -> None:
        self._drive_timer.stop()
        self._drive_send()

    def _zoom_changed(self) -> None:
        self.spectrum.set_zoom(self.zoom.currentData())

    @staticmethod
    def wf_scheme() -> str:
        name = load_choice("waterfall_scheme", DEFAULT_WATERFALL)
        return name if name in WATERFALL_SCHEMES else DEFAULT_WATERFALL

    @staticmethod
    def sp_scheme() -> str:
        name = load_choice("spectrum_scheme", DEFAULT_SPECTRUM)
        return name if name in SPECTRUM_SCHEMES else DEFAULT_SPECTRUM

    def show_about(self) -> None:
        QMessageBox.about(self, "About X6100 TCI Remote", (
            "<h3>X6100 TCI Remote %s</h3>"
            "<p>An independent desktop remote controller for the Xiegu X6100 and X6200.</p>"
            "<p>This app is <b>not affiliated with OpenX6X00</b>. It works alongside the OpenX6X00 firmware "
            "(<a href='https://openx6x00.org/'>https://openx6x00.org/</a>), which provides the TCI and panel "
            "servers it talks to, and works only with that firmware, not with the stock Xiegu firmware.</p>"
            "<p><b>Credits:</b> thanks to <b>all the authors and contributors of OpenX6X00</b>, including "
            "RF.Guru (Joeri Van Dooren ON6URE), for their open-source firmware.</p>"
            "<p>Free and open for anyone to use and develop (LGPL-2.1-or-later). "
            "<b>You are responsible for what goes on air.</b></p>"
            "<p>Bugs and reports: <a href='https://github.com/amystikis/x6100-tci-remote'>"
            "https://github.com/amystikis/x6100-tci-remote</a></p>") % __version__)

    def _tick_clock(self) -> None:
        self.clock.setText(datetime.now(timezone.utc).strftime("%H:%M:%S"))

    def _waterfall_scheme_chosen(self, name: str) -> None:
        save_choice("waterfall_scheme", name)
        self.spectrum.set_waterfall_scheme(name)

    @staticmethod
    def spot_scheme() -> str:
        name = load_choice("spot_scheme", DEFAULT_SPOTS)
        return name if name in SPOT_SCHEMES else DEFAULT_SPOTS

    def _spot_scheme_chosen(self, name: str) -> None:
        save_choice("spot_scheme", name)
        self.spectrum.set_spot_scheme(name)

    def _spectrum_scheme_chosen(self, name: str) -> None:
        save_choice("spectrum_scheme", name)
        self.spectrum.set_spectrum_scheme(name)

    @staticmethod
    def noise_floor_settings() -> tuple[bool, float, float]:
        try:
            return (load_choice("nf_auto", "1") != "0", float(load_choice("nf_offset", "0")),
                    float(load_choice("nf_contrast", "1")))
        except ValueError:
            return True, 0.0, 1.0

    @staticmethod
    def trace_floor_settings() -> tuple[bool, float]:
        try:
            return load_choice("tr_auto", "1") != "0", float(load_choice("tr_offset", "0"))
        except ValueError:
            return True, 0.0

    def _build_settings_dialog(self) -> None:
        """Settings dialog: 'Connection' (radio address + connect) and 'Display' (colour schemes, applied at once)."""
        dlg = self.settings_dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        lay = QVBoxLayout(dlg)
        tabs = self.settings_tabs = QTabWidget()
        lay.addWidget(tabs)

        conn = QWidget()
        cv = QVBoxLayout(conn)
        cl = QHBoxLayout()
        cl.addWidget(QLabel("Radio"))
        cl.addWidget(self.addr, 1)
        cl.addWidget(self.connect_btn)
        cv.addLayout(cl)
        pl = QHBoxLayout()
        self.pair_state = QLabel("")
        pl.addWidget(QLabel("Radio keys"))
        pl.addWidget(self.pair_state, 1)
        self.pair_btn2 = _btn("Pair...", slot=self.pair_panel)
        self.pair_btn2.setToolTip("Pair this app with the radio (6-digit code shown on the radio's screen)")
        pl.addWidget(self.pair_btn2)
        cv.addLayout(pl)
        cv.addStretch(1)
        tabs.addTab(conn, "Connection")
        self._update_pair_state()

        page = QWidget()
        form = QFormLayout(page)
        wf, sp = QComboBox(), QComboBox()
        wf.addItems(list(WATERFALL_SCHEMES))
        sp.addItems(list(SPECTRUM_SCHEMES))
        wf.setCurrentText(self.wf_scheme())
        sp.setCurrentText(self.sp_scheme())
        wf.currentTextChanged.connect(self._waterfall_scheme_chosen)
        sp.currentTextChanged.connect(self._spectrum_scheme_chosen)
        form.addRow("Waterfall colours", wf)
        form.addRow("Spectrum colour", sp)
        spots = QComboBox()
        spots.addItems(list(SPOT_SCHEMES))
        spots.setCurrentText(self.spot_scheme())
        spots.currentTextChanged.connect(self._spot_scheme_chosen)
        form.addRow("DX call-sign colour", spots)
        auto = QCheckBox("Auto noise floor (follows the noise by itself)")
        floor, contrast = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        floor.setRange(-10, 30)
        contrast.setRange(50, 200)
        floor_lbl, contrast_lbl = QLabel(), QLabel()
        nf = self.noise_floor_settings()
        auto.setChecked(nf[0])
        floor.setValue(round(nf[1] * 100))
        contrast.setValue(round(nf[2] * 100))

        def show_values() -> None:
            floor_lbl.setText("%+d %%" % floor.value())
            contrast_lbl.setText("%d %%" % contrast.value())

        def apply_noise_floor() -> None:
            show_values()
            save_choice("nf_auto", "1" if auto.isChecked() else "0")
            save_choice("nf_offset", str(floor.value() / 100))
            save_choice("nf_contrast", str(contrast.value() / 100))
            self.spectrum.set_noise_floor(auto.isChecked(), floor.value() / 100, contrast.value() / 100)
        auto.toggled.connect(apply_noise_floor)
        floor.valueChanged.connect(apply_noise_floor)
        contrast.valueChanged.connect(apply_noise_floor)
        show_values()
        tr_auto, tr_floor, tr_lbl = (QCheckBox("Auto noise floor on the spectrum trace"),
                                     QSlider(Qt.Orientation.Horizontal), QLabel())
        tr_floor.setRange(-10, 30)
        tr = self.trace_floor_settings()
        tr_auto.setChecked(tr[0])
        tr_floor.setValue(round(tr[1] * 100))

        def apply_trace_floor() -> None:
            tr_lbl.setText("%+d %%" % tr_floor.value())
            save_choice("tr_auto", "1" if tr_auto.isChecked() else "0")
            save_choice("tr_offset", str(tr_floor.value() / 100))
            self.spectrum.set_trace_floor(tr_auto.isChecked(), tr_floor.value() / 100)
        tr_auto.toggled.connect(apply_trace_floor)
        tr_floor.valueChanged.connect(apply_trace_floor)
        tr_lbl.setText("%+d %%" % tr_floor.value())
        form.addRow(tr_auto)
        row = QHBoxLayout()
        row.addWidget(tr_floor, 1)
        tr_lbl.setMinimumWidth(48)
        row.addWidget(tr_lbl)
        form.addRow("Spectrum floor", row)
        form.addRow(auto)
        for label, slider, value_lbl in (("Noise floor", floor, floor_lbl), ("Contrast", contrast, contrast_lbl)):
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            value_lbl.setMinimumWidth(48)
            row.addWidget(value_lbl)
            form.addRow(label, row)
        form.addRow(_btn("Reset", slot=lambda: (auto.setChecked(True), floor.setValue(0), contrast.setValue(100),
                                                tr_auto.setChecked(True), tr_floor.setValue(0))))
        tabs.addTab(page, "Display")
        tabs.addTab(self._build_operating_tab(), "Operating")
        tabs.addTab(self._build_keyboard_tab(), "Keyboard")
        lay.addWidget(_btn("Close", slot=lambda: dlg.accept()), 0, Qt.AlignmentFlag.AlignRight)

    # keys that already do something else in the app, so they cannot be the PTT key
    RESERVED_KEYS = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Escape, Qt.Key.Key_F11, Qt.Key.Key_Tab,
                     Qt.Key.Key_Backtab)

    @classmethod
    def _key_from_text(cls, text: str) -> int:
        seq = QKeySequence(text)
        k = seq[0].key().value if seq.count() else 0
        return k if k and Qt.Key(k) not in cls.RESERVED_KEYS else Qt.Key.Key_Space.value

    def _build_operating_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        on = QCheckBox("Automatic mode by band and segment")
        on.setChecked(self._auto_mode_on)

        def toggled(v: bool) -> None:
            self._auto_mode_on = v
            save_flag("auto_mode", v)

        on.toggled.connect(toggled)
        form.addRow(on)
        form.addRow(QLabel("When the frequency moves into another band or segment the mode follows:\n"
                           "  - 160, 80, 60 and 40 m: LSB; 30 m and up: USB\n"
                           "  - digital segments of the radio's band plan: DIGU\n"
                           "  - CW segments: CW\n"
                           "Not while transmitting or with the dial locked. AM/FM are never changed, and a mode you\n"
                           "pick by hand stays while you tune inside the same segment."))
        self.auto_mode_check = on
        row = QHBoxLayout()
        self.rec_dir_lbl = QLabel(str(self.rec_dir()))
        self.rec_dir_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.rec_dir_lbl, 1)
        row.addWidget(_btn("Choose...", slot=self._choose_rec_dir))
        form.addRow("Recordings folder", row)
        return page

    def _choose_rec_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Recordings folder", str(self.rec_dir()))
        if d:
            save_choice("rec_dir", d)
            self.rec_dir_lbl.setText(d)

    def _build_keyboard_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        on = QCheckBox("Hold a key to transmit (push-to-talk) while this window is active")
        on.setChecked(self._ptt_key_on)
        edit = QKeySequenceEdit(QKeySequence(Qt.Key(self._ptt_key)))
        edit.setToolTip("Click, then press the key to use. Keys with Ctrl/Alt/Meta and keys that already do "
                        "something else (arrows, Esc, F11, Tab) are not accepted.")
        note = QLabel("")
        note.setWordWrap(True)

        def toggled(v: bool) -> None:
            self._ptt_key_on = v
            save_flag("ptt_key", v)
            edit.setEnabled(v)
            if not v and self._space_ptt:
                self._release_timer.stop()
                self._space_ptt = False
                self.set_ptt(False)

        def changed(seq: QKeySequence) -> None:
            if seq.isEmpty():
                return
            first = seq[0]
            k = first.key().value
            if (first.keyboardModifiers() != Qt.KeyboardModifier.NoModifier or Qt.Key(k) in self.RESERVED_KEYS
                    or Qt.Key(k) in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_Shift)):
                note.setText("That key cannot be used. Pick one without Ctrl/Alt/Meta that is not an arrow, Esc, "
                             "F11 or Tab.")
                edit.setKeySequence(QKeySequence(Qt.Key(self._ptt_key)))
                return
            self._ptt_key = k
            save_choice("ptt_key", QKeySequence(Qt.Key(k)).toString())
            note.setText("PTT key: %s" % QKeySequence(Qt.Key(k)).toString())
            edit.setKeySequence(QKeySequence(Qt.Key(k)))          # keep one key only

        on.toggled.connect(toggled)
        edit.keySequenceChanged.connect(changed)
        edit.setEnabled(self._ptt_key_on)
        reset = _btn("Reset to Space", slot=lambda: (edit.setKeySequence(QKeySequence(Qt.Key.Key_Space)),
                                                     changed(QKeySequence(Qt.Key.Key_Space))))
        form.addRow(on)
        form.addRow("PTT key", edit)
        form.addRow(reset)
        form.addRow(note)
        form.addRow(QLabel("Still needs 'Enable transmit' ticked. Ignored while typing in a text or number field,\n"
                           "and the radio is unkeyed when the window loses focus."))
        self.ptt_key_edit, self.ptt_key_check = edit, on
        return page

    def open_settings(self) -> None:
        self.settings_dlg.exec()

    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme_name = name
        save_choice("theme", name)
        apply_palette(THEMES[name])
        self.setStyleSheet(build_style(THEMES[name]))
        for w in (self.freq, self.smeter):
            w.update()

    def _show_group(self, key: str, box: QGroupBox, on: bool) -> None:
        save_flag("show_" + key, on)
        box.setVisible(on)

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
        if not self._auto_mode_on:                  # with automatic mode the new frequency decides the mode
            self.w.send("modulation", 0, mode)
        self.w.send("vfo", 0, 0, hz)

    # audio ------------------------------------------------------------------------------
    def toggle_sound(self, on: bool) -> None:
        if on:
            if not self.rx.start(self.state.audio_sample_rate or 48000):
                self.sound.setChecked(False)
                self.statusBar().showMessage("No audio output available", 5000)
                return
            self._rec_started_audio = False         # the user wants the stream now; REC no longer owns it
            self.w.set_audio(True)
        else:
            self.rx.stop()
            if self._recording:                     # keep the stream on for the recording; REC turns it off later
                self._rec_started_audio = True
                return
            self.w.set_audio(False)

    # recorder ---------------------------------------------------------------------------
    def rec_dir(self) -> Path:
        return Path(load_choice("rec_dir", str(default_rec_dir())))

    def open_rec_folder(self) -> None:
        d = self.rec_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def toggle_record(self, on: bool) -> None:
        if on:
            if not self.w.client:
                self.rec_btn.blockSignals(True)
                self.rec_btn.setChecked(False)
                self.rec_btn.blockSignals(False)
                self.statusBar().showMessage("Connect to the radio first", 5000)
                return
            self._recording = True
            self._rec_shown = -1
            self.rec_time.setText("00:00")
            self.rec_info.setText("recording...")
            if not self.sound.isChecked():           # recording does not need the speaker, only the audio stream
                self._rec_started_audio = True
                self.w.set_audio(True)
        else:
            self._stop_record()

    def _on_rx_audio(self, data: bytes, rate: int) -> None:
        if not self._recording:
            return
        try:
            if self._rec is None:
                path = unique_path(self.rec_dir(), recording_name(self.state.freq, self.state.mode))
                self._rec = WavRecorder(path, rate)
                self.rec_info.setText(path.name)
            elif rate != self._rec.rate:
                self._stop_record("Recording stopped: the radio changed its audio sample rate")
                return
            self._rec.write(data)
        except OSError as e:
            self._stop_record("Recording stopped: %s" % e)
            return
        sec = int(self._rec.seconds)
        if sec != self._rec_shown:
            self._rec_shown = sec
            self.rec_time.setText("%02d:%02d" % (sec // 60, sec % 60))
        if self._rec.seconds >= MAX_REC_S:
            self._stop_record("Recording stopped after %d minutes" % (MAX_REC_S // 60))

    def _stop_record(self, message: str = "") -> None:
        rec, self._rec = self._rec, None
        self._recording = False
        self.rec_btn.blockSignals(True)
        self.rec_btn.setChecked(False)
        self.rec_btn.blockSignals(False)
        if rec is not None:
            rec.close()
            size = rec.path.stat().st_size / 1e6 if rec.path.exists() else 0.0
            self.rec_info.setText(rec.path.name)
            self.statusBar().showMessage(message or "Saved %s (%.0f s, %.1f MB)" % (rec.path, rec.seconds, size), 10000)
        else:
            self.rec_info.setText("")
            if message:
                self.statusBar().showMessage(message, 8000)
        if self._rec_started_audio:
            self._rec_started_audio = False
            if not self.sound.isChecked():
                self.w.set_audio(False)

    # playback-transmit --------------------------------------------------------------------
    def choose_play_file(self) -> None:
        start = load_choice("play_dir", str(self.rec_dir()))
        path, _ = QFileDialog.getOpenFileName(self, "Audio file to transmit", start, "WAV audio (*.wav);;All files (*)")
        if path:
            self.load_play_file(path)

    def load_play_file(self, path: str) -> bool:
        try:
            samples, rate = read_audio(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Audio file", "Cannot use %s:\n%s" % (path, e))
            return False
        self._play_samples, self._play_path = (samples, rate), Path(path)
        save_choice("play_dir", str(Path(path).parent))
        self._show_play_name()
        self._update_play_buttons()
        return True

    def _show_play_name(self, extra: str = "") -> None:
        if self._play_samples is None or self._play_path is None:
            self.play_name.setText("No file selected")
            return
        secs = len(self._play_samples[0]) / self._play_samples[1]
        self.play_name.setText(extra or "%s  (%d:%02d)" % (self._play_path.name, secs // 60, secs % 60))
        self.play_name.setToolTip(str(self._play_path))

    def _play_level_changed(self, value: int) -> None:
        self.play_level_lbl.setText("%d%%" % value)
        if self._player is not None:
            self._player.gain = value / 100

    def _update_play_buttons(self) -> None:
        busy = self._player is not None
        ready = (self._play_samples is not None and self.tx_enable.isChecked() and bool(self.w.client)
                 and not self._ptt_on)
        self.play_btn.setEnabled(ready)
        self.play_stop.setEnabled(busy)
        self.play_choose.setEnabled(not busy)

    def play_file(self, confirm: bool = True) -> None:
        """Transmit the chosen file. Same guards as the PTT button, plus a confirmation, because it goes on air."""
        if self._ptt_on or self._player is not None:
            return
        if not self.tx_enable.isChecked() or not self.w.client:
            self.statusBar().showMessage("Tick 'Enable transmit controls' and connect first", 5000)
            return
        if self._play_samples is None:
            self.statusBar().showMessage("Choose an audio file first", 5000)
            return
        samples, rate = self._play_samples
        player = FilePlayer(samples, rate, self.play_level.value() / 100, self.state.audio_sample_rate or 48000)
        if player.seconds > self.tx_limit.value():
            QMessageBox.warning(self, "Transmit file",
                                "The file is %.0f s long but 'Auto-unkey after' is %d s.\nRaise that limit or choose a "
                                "shorter file." % (player.seconds, self.tx_limit.value()))
            return
        if confirm:
            st = self.state
            ask = QMessageBox.question(
                self, "Transmit file",
                "Transmit %s (%.0f s)\non %.3f kHz %s at %s?\n\nYou are responsible for what goes on air." % (
                    self._play_path.name if self._play_path else "the file", player.seconds, st.freq / 1000,
                    MODE_LABELS.get(st.mode, st.mode), self._power_text(self.drive.value())),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if ask != QMessageBox.StandardButton.Yes:
                return
        self._player = player
        self.set_ptt(True, source=player.read_frames)
        if not self._ptt_on:                          # refused
            self._player = None
            self._update_play_buttons()
            return
        self._play_timer.start()
        self._update_play_buttons()

    def stop_playback(self) -> None:
        if self._player is not None:
            self.set_ptt(False)
            self.statusBar().showMessage("Playback stopped", 5000)

    def _end_playback(self) -> None:
        self._play_timer.stop()
        self._player = None
        self._show_play_name()
        self._update_play_buttons()

    def _play_tick(self) -> None:
        p = self._player
        if p is None:
            self._play_timer.stop()
            return
        if not self.w.client or not self._ptt_on:
            self.set_ptt(False)
            return
        if p.done:
            self.set_ptt(False)
            self.statusBar().showMessage("Playback finished", 5000)
            return
        self._show_play_name("Transmitting  %.1f / %.1f s" % (p.position_s, p.seconds))

    # transmit ---------------------------------------------------------------------------
    def tx_enable_changed(self, on: bool) -> None:
        for wdg in (self.ptt, self.drive, self.tx_limit):
            wdg.setEnabled(on)
        self.pc_mic.setEnabled(on and AUDIO_OK)
        if not on and self._ptt_on:
            self.set_ptt(False)
        self._update_key_buttons()
        self._update_play_buttons()

    def set_ptt(self, on: bool, external: bool = False, source=None) -> None:
        """Key or unkey. ``source`` (a ``read_frames(n)`` callable) sends that audio instead of the microphone."""
        if on and (not self.tx_enable.isChecked() or not self.w.client):
            return
        if on == self._ptt_on:
            return
        self._ptt_on = on
        self._ptt_external = on and external
        use_pc_mic = self.pc_mic.isChecked() and on and source is None
        if on and source is not None:
            self.w.set_tx_source(source)
        elif on and use_pc_mic:
            if not self.mic.start():
                self.statusBar().showMessage("Microphone unavailable", 5000)
                self._ptt_on = False
                return
            self.w.set_tx_source(self.mic.read_frames)
        self.w.set_ptt(on, use_pc_mic or source is not None)
        if on:
            self._tx_since = time.monotonic()
            self.tx_timer.start()
        else:
            self.tx_timer.stop()
            self.mic.stop()
            self.w.set_tx_source(None)
            if self._player is not None:
                self._end_playback()
        self.ptt.setDown(on)                       # show the state also when keyed/unkeyed by key, timer or focus loss
        self._update_key_buttons()
        self._update_play_buttons()

    def _tx_watchdog(self) -> None:
        if self._ptt_on and time.monotonic() - self._tx_since > self.tx_limit.value():
            self.set_ptt(False)
            self.statusBar().showMessage("Auto-unkeyed: transmit time limit reached", 8000)

    def toggle_fullscreen(self) -> None:
        """Full screen without window borders; the same button, F11 and the View menu leave it again (also Esc)."""
        on = not self.isFullScreen()
        if on:
            self.showFullScreen()
        else:
            self.showNormal()
        self.fullscreen_act.setChecked(on)
        self.fullscreen_btn.setText("⛶ Exit full screen" if on else "⛶ Full screen")

    # keyboard / focus -----------------------------------------------------------------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        k, big = e.key(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        mult = 10 if big else 1
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.tune_by((1 if k == Qt.Key.Key_Right else -1) * self.step.currentData() * mult)
        elif k == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, e) -> bool:
        """Hold the PTT key (Space by default, set in Settings > Keyboard) to transmit while this window is the active
        one. It is taken before the focused widget sees it (a checkbox or button would otherwise be toggled), except
        while typing in a text or number field."""
        t = e.type()
        if t not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) or e.key() != self._ptt_key:
            return False
        if t == QEvent.Type.KeyRelease and self._space_ptt:            # always honour the release of a held key
            if not e.isAutoRepeat():
                self._release_timer.start()      # not at once: some systems send release+press when the key repeats
            return True
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if not self._ptt_key_on or e.modifiers() & mods:
            return False
        if QApplication.activeWindow() is not self:                    # another window or a dialog is in front
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QPlainTextEdit)) or (
                isinstance(focus, QComboBox) and focus.isEditable()):
            return False                                               # let the user type a space
        if t == QEvent.Type.KeyPress:
            if self._release_timer.isActive():
                self._release_timer.stop()                             # a repeat, not a real release: stay keyed
            elif not e.isAutoRepeat() and not self._space_ptt:
                self._space_ptt = True
                self.set_ptt(True)
                if not self._ptt_on:
                    self._space_ptt = False                            # refused (transmit not enabled / no radio)
            return True
        return True

    def _ptt_key_released(self) -> None:
        self._space_ptt = False
        self.set_ptt(False)

    def changeEvent(self, e) -> None:
        if (e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self._ptt_on
                and not self._ptt_external):
            self._space_ptt = False
            self.set_ptt(False)                    # never stay keyed after losing focus (button/Space PTT)
            self.statusBar().showMessage("Unkeyed: the window lost focus", 8000)
        super().changeEvent(e)

    def closeEvent(self, e) -> None:
        self.set_ptt(False)
        if self._recording:
            self._stop_record()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self.cmd_server is not None:
            self.cmd_server.stop()
        if self.isFullScreen():
            self.showNormal()                      # remember the normal window, not the full-screen size
        save_window_geometry(bytes(self.saveGeometry()))
        save_band_memory(self.band_mem)
        self.rx.stop()
        self.mic.stop()
        self.w.shutdown()
        super().closeEvent(e)

    # connection ---------------------------------------------------------------------------------
    @staticmethod
    def valid_radio_address(text: str) -> bool:
        """host, host:port or a ws:// URL, where host is an IPv4 address or a hostname."""
        t = text.strip()
        if t.startswith(("ws://", "wss://")):
            t = t.split("://", 1)[1].split("/", 1)[0]
        host, sep, port = t.partition(":")
        if sep and not (port.isdigit() and 0 < int(port) < 65536):
            return False
        parts = host.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            return all(int(p) <= 255 for p in parts)
        label = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        return bool(re.fullmatch(label + r"(\." + label + ")*", host))

    def auto_connect_last(self) -> bool:
        """At start-up: connect to the radio used last time, if it was saved and its address is valid."""
        radios = load_radios()
        if not radios or not self.valid_radio_address(radios[0]):
            return False
        self.addr.setEditText(radios[0])
        self.toggle_connection()
        return True

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
        self.w.set_panel_token(load_panel_token(self._panel_url))
        self._auto_key = None
        self.w.connect_to(url)
        if self.spectrum_act.isChecked():
            self.spectrum.clear()
            self.spectrum.set_plan([])
            self.spectrum.set_spots([])
            self.cw_view.clear()
            self.status_strip.hide()
            self.spectrum.set_message("Waiting for spectrum...")
            self.w.connect_panel(self._panel_url)

    def _apply_cw_tuner(self, mode: str, bw: int) -> None:
        """A CW signal is tuned when it sits one CW pitch from the VFO (above in CW, below in CW-R): put the passband
        overlay and the tuner meter there."""
        target = target_hz(mode, self.w.info.cw_pitch)
        self.spectrum.set_passband(int(target - bw / 2), int(target + bw / 2))
        self.spectrum.set_cw_tuner(bw, target)

    def clear_cw(self) -> None:
        """Clear the CW text. The decoder history lives in the worker's PanelInfo and is re-shown on every new
        message, so it has to be emptied too or the old letters come straight back."""
        self.w.info.cw_text = ""
        self.cw_view.clear()

    def on_panel_info(self, kind: str) -> None:
        info = self.w.info
        if kind == "plan":
            self.spectrum.set_plan(info.plan)
            self._auto_mode(self.state.freq, apply=False)       # the plan refines the rule; only note where we are
        elif kind == "spots":
            self.spectrum.set_spots(info.spots)
        elif kind in ("state", "ft8", "role"):
            self._update_status_strip()
            self._update_key_buttons()
            st = self.state
            if kind == "state" and st.mode in ("cw", "cwr"):
                self._apply_cw_tuner(st.mode, abs(st.filter_hi - st.filter_lo))     # the pitch may have changed
        elif kind == "t":
            if self.tx_meter.isVisible():
                self._tx_meter_update()
        elif kind == "cw":
            self.cw_view.setPlainText(info.cw_text)
            self.cw_view.verticalScrollBar().setValue(self.cw_view.verticalScrollBar().maximum())
            self._update_cw_visibility()

    def _tx_meter_update(self) -> None:
        i = self.w.info
        self.tx_meter.update_values(i.tx_power, i.tx_swr, i.tx_alc)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.tx_meter.isVisible():
            self.tx_meter.reposition(self.spectrum)

    # OS hotkey support (x6100-tci-remote --ptt on|off|toggle) -----------------------------------------------
    def start_command_server(self, name: str | None = None) -> bool:
        self.cmd_server = CommandServer(self.remote_command, name)
        return self.cmd_server.start()

    def remote_command(self, cmd: str) -> str:
        """Same guards as the PTT button; the auto-unkey timer still applies."""
        action = cmd.split()[-1]
        if action == "off":
            self.set_ptt(False)
            return "ok: receive"
        if not self.tx_enable.isChecked():
            return "refused: 'Enable transmit controls' is not ticked in the app"
        if not self.w.client or not self.state.ready:
            return "refused: not connected to the radio"
        want = (not self._ptt_on) if action == "toggle" else True
        if want != self._ptt_on:
            self.set_ptt(want, external=True)
            self.statusBar().showMessage("PTT %s by hotkey" % ("ON" if want else "off"), 4000)
        if want and not self._ptt_on:
            return "error: could not start transmit"
        return "ok: transmitting" if self._ptt_on else "ok: receive"

    # radio keys ----------------------------------------------------------------------------------------
    def _set_on(self, btn: QPushButton, on: bool) -> None:
        if btn.property("on") != on:
            btn.setProperty("on", on)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_key_buttons(self) -> None:
        info = self.w.info
        paired = info.role in ("operate", "admin")
        for b in self._key_buttons.values():
            b.setEnabled(self._panel_up)
        self.atu_tune.setEnabled(self._panel_up and paired and self.tx_enable.isChecked() and not self._ptt_on)
        self.pair_btn.setVisible(self._panel_up and not paired)
        self._update_pair_state()
        st = info.state
        self._set_on(self._key_buttons["PRE"], bool(st.get("pre")))
        self._set_on(self._key_buttons["ATU"], bool(st.get("atu")))
        self._set_on(self._key_buttons["AB"], bool(st.get("vfo")))

    def _update_pair_state(self) -> None:
        paired = self.w.info.role in ("operate", "admin")
        if not self._panel_up:
            text = "Not available (the panel server is not connected)"
        elif paired:
            text = "Paired (%s)" % self.w.info.role
        else:
            text = "Not paired: the radio keys (PRE, A/B, V/M, FST, ATU) are off"
        self.pair_state.setText(text)
        self.pair_btn2.setEnabled(self._panel_up)
        self.pair_btn2.setText("Re-pair..." if paired else "Pair...")

    def press_key(self, key: str) -> None:
        self.w.press_key(key)

    def tune_atu(self) -> None:
        if not self.tx_enable.isChecked() or self._ptt_on:
            return
        self.statusBar().showMessage("ATU tuning: the radio is transmitting a carrier", 4000)
        self.w.press_key("ATU", 1.2)                 # a long press starts a tune cycle, as on the radio's page

    def pair_panel(self) -> None:
        self.w.request_pair_code()                    # "pair?": the radio now shows a code on its own screen
        code, ok = QInputDialog.getText(self, "Pair with the radio",
                                        "A 6-digit code is now on the radio's screen (for two minutes).\n"
                                        "If it is gone: Settings > General > BROWSER REMOTE > Pair code.\n\n"
                                        "Code:")
        code = code.strip()
        if not ok:
            return
        if not (code.isdigit() and len(code) == 6):
            self.statusBar().showMessage("The pairing code is 6 digits", 5000)
            return
        name = ("x6100-tci-remote on " + platform.node())[:32].replace("_", "-")
        self.w.pair_panel(code, "".join(c if c.isalnum() or c in " .-" else "-" for c in name))

    def on_paired(self, role: str, key: str) -> None:
        if key:
            url = self._panel_url or ""
            save_panel_token(url, key)
            self.w.set_panel_token(key)
            self.statusBar().showMessage("Paired as %s. The key is saved for this radio." % role, 8000)
        else:
            self.statusBar().showMessage("The radio accepted the pairing (%s) but I found no key in its reply, "
                                         "so it will not survive a restart." % role, 10000)
        self._update_key_buttons()

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
        self._panel_up = state == "connected"
        self._update_key_buttons()
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
        if state == "disconnected" and self._recording:
            self._stop_record("Recording stopped: disconnected from the radio")
        if state == "disconnected":
            self._update_play_buttons()
        if state == "disconnected" and not detail:
            self.connect_btn.setText("Connect")
        else:
            self.connect_btn.setText("Disconnect")         # connected, connecting or retrying: the button cancels it
        if state == "connected":
            self.refresh("")
