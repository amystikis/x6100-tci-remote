"""Custom-painted widgets: frequency display and S-meter."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QWidget

from ..tci.protocol import dbm_to_s

# Palette of the custom-painted widgets; replaced by apply_palette() when the theme changes.
AMBER = QColor("#f0a830")
PANEL = QColor("#0e1626")
EDGE = QColor("#22324f")
DIM = QColor("#5b6b88")
GREEN = QColor("#3ddc97")
RED = QColor("#ff5a5a")
METER_BG = QColor("#0a1120")
PEAK = QColor("#dbe4f3")


def apply_palette(t) -> None:
    global AMBER, PANEL, EDGE, DIM, GREEN, RED, METER_BG, PEAK
    AMBER, PANEL, EDGE, DIM = QColor(t.accent), QColor(t.panel), QColor(t.edge), QColor(t.dim)
    GREEN, RED, METER_BG, PEAK = QColor(t.green), QColor(t.red), QColor(t.meter_bg), QColor(t.peak)


def format_freq(hz: int) -> str:
    mhz, rem = divmod(max(0, int(hz)), 1_000_000)
    khz, h = divmod(rem, 1000)
    return "%d.%03d.%03d" % (mhz, khz, h)


class FrequencyDisplay(QWidget):
    """Big VFO readout. Mouse wheel over a digit, or click its upper/lower half, tunes by
    that digit's place value; double-click to type a frequency.

    Click a digit to select it (shown with an underline), then the Left/Right arrow keys move
    the selection and Up/Down change the selected digit's place value."""

    tune = Signal(int)            # delta in Hz
    entered = Signal()            # double-click: ask for a typed frequency

    def __init__(self) -> None:
        super().__init__()
        self.freq = 0
        self.locked = False
        self.setMinimumHeight(86)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        f = QFont()
        f.setFamilies(["DejaVu Sans Mono", "Liberation Mono", "Consolas", "Menlo", "Courier New", "monospace"])
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(44)
        f.setWeight(QFont.Weight.DemiBold)
        self._font = f
        self.setFont(f)
        self._hover = -1
        self._selected_place: int | None = None       # place value (1, 10, 100, ...) selected via click/arrows

    def set_freq(self, hz: int) -> None:
        self.freq = hz
        self.update()

    # layout helpers -------------------------------------------------------------
    def _digits(self) -> list[tuple[int, QRectF, int]]:
        """[(char_index, rect, place_value)] for each digit in the formatted text."""
        text = format_freq(self.freq)
        cw = QFontMetricsF(self._font).horizontalAdvance("0")
        total = cw * len(text)
        x0 = (self.width() - total) / 2
        out, place = [], len([c for c in text if c.isdigit()]) - 1
        for i, ch in enumerate(text):
            if ch.isdigit():
                out.append((i, QRectF(x0 + i * cw, 0, cw, self.height()), 10 ** place))
                place -= 1
        return out

    def _hit(self, x: float):
        for i, r, place in self._digits():
            if r.left() <= x < r.right():
                return i, place
        return None

    # events --------------------------------------------------------------------
    def wheelEvent(self, e) -> None:
        hit = self._hit(e.position().x())
        if hit and not self.locked:
            self.tune.emit(hit[1] * (1 if e.angleDelta().y() > 0 else -1))
        e.accept()

    def mousePressEvent(self, e) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        hit = self._hit(e.position().x())
        if hit:
            self._selected_place = hit[1]
            self.update()
        if hit and not self.locked and e.button() == Qt.MouseButton.LeftButton:
            self.tune.emit(hit[1] * (1 if e.position().y() < self.height() / 2 else -1))

    def mouseDoubleClickEvent(self, e) -> None:
        self.entered.emit()

    def mouseMoveEvent(self, e) -> None:
        hit = self._hit(e.position().x())
        h = hit[0] if hit else -1
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = -1
        self.update()

    def focusInEvent(self, e) -> None:
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        self.update()
        super().focusOutEvent(e)

    def keyPressEvent(self, e) -> None:
        places = [p for _, _, p in self._digits()]
        key = e.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and places:
            if self._selected_place not in places:
                idx = 0 if key == Qt.Key.Key_Right else len(places) - 1
            else:
                idx = places.index(self._selected_place) + (1 if key == Qt.Key.Key_Right else -1)
                idx = max(0, min(len(places) - 1, idx))
            self._selected_place = places[idx]
            self.update()
            e.accept()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and places:
            if self._selected_place not in places:
                self._selected_place = places[-1]
            if not self.locked:
                self.tune.emit(self._selected_place * (1 if key == Qt.Key.Key_Up else -1))
            e.accept()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), PANEL)
        p.setPen(QPen(EDGE, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.setFont(self._font)
        text = format_freq(self.freq)
        digits = {i: r for i, r, _ in self._digits()}
        places = {i: pl for i, _, pl in self._digits()}
        for i, ch in enumerate(text):
            if ch.isdigit():
                r = digits[i]
                if i == self._hover and not self.locked:
                    hover = QColor(AMBER)
                    hover.setAlpha(38)
                    p.fillRect(r.adjusted(1, 8, -1, -8), hover)
                p.setPen(DIM if self.locked else AMBER)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, ch)
                if self.hasFocus() and places[i] == self._selected_place:
                    p.setPen(QPen(AMBER, 2))
                    p.drawLine(int(r.left() + 6), int(r.bottom() - 6), int(r.right() - 6), int(r.bottom() - 6))
            else:
                cw = QFontMetricsF(self._font).horizontalAdvance("0")
                x = (self.width() - cw * len(text)) / 2 + i * cw
                p.setPen(DIM)
                p.drawText(QRectF(x, 0, cw, self.height()), Qt.AlignmentFlag.AlignCenter, ch)


class SMeter(QWidget):
    """S1..S9, +20, +40, +60 bar with a short peak hold and a dBm readout."""

    def __init__(self) -> None:
        super().__init__()
        self.dbm = -140.0
        self.peak = 0.0
        self.setMinimumHeight(46)

    def set_dbm(self, dbm: float) -> None:
        self.dbm = dbm
        _, frac = dbm_to_s(dbm)
        self.peak = max(frac, self.peak - 0.01)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), PANEL)
        label, frac = dbm_to_s(self.dbm)
        bar = QRectF(10, 8, w - 150, 14)
        p.setPen(QPen(EDGE, 1))
        p.setBrush(METER_BG)
        p.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar.left(), bar.top(), bar.width() * frac, bar.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GREEN if frac <= 0.6 else AMBER if frac <= 0.8 else RED)
        p.drawRoundedRect(fill, 3, 3)
        x = bar.left() + bar.width() * self.peak
        p.setPen(QPen(PEAK, 2))
        p.drawLine(int(x), int(bar.top()), int(x), int(bar.bottom()))
        p.setPen(DIM)
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        marks = [(1, "1"), (3, "3"), (5, "5"), (7, "7"), (9, "9")]
        for s, t in marks:
            xx = bar.left() + bar.width() * ((s - 1) / 8 * 0.6)
            p.drawText(QRectF(xx - 10, 24, 20, 14), Qt.AlignmentFlag.AlignCenter, t)
        for plus, t in ((20, "+20"), (40, "+40"), (60, "+60")):
            xx = bar.left() + bar.width() * (0.6 + plus / 60 * 0.4)
            p.drawText(QRectF(xx - 14, 24, 28, 14), Qt.AlignmentFlag.AlignCenter, t)
        big = QFont(self.font())
        big.setPointSize(15)
        big.setWeight(QFont.Weight.DemiBold)
        p.setFont(big)
        p.setPen(AMBER)
        p.drawText(QRectF(w - 130, 2, 60, h - 4), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, label)
        small.setPointSize(9)
        p.setFont(small)
        p.setPen(DIM)
        p.drawText(QRectF(w - 66, 2, 60, h - 4), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "%d dBm" % round(self.dbm))


class TxMeterPopup(QFrame):
    """Small overlay with power, SWR and ALC, shown over the main window while transmitting.

    It is a child widget (not a separate window) so it can never take focus.
    (The app unkeys when its window loses focus.)"""

    POWER_SCALES = (5, 10, 25, 50, 100)
    SWR_MAX = 3.0                      # bar full scale; the number is shown as is
    SWR_WARN = 2.0                     # above this the SWR bar is amber, from SWR_RED up it is red
    SWR_RED = 2.5
    COL_PWR, COL_SWR_OK, COL_ALC = "#9aa5b8", "#7ee2a8", "#7cc4ff"     # grey, light green, light blue
    COL_AMBER, COL_RED = "#f0a830", "#ff5a5a"
    ALC_MAX = 10.0                     # observed 0-8 on a real radio; the unit is not documented

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tx_meter")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QFrame#tx_meter { background:rgba(10,17,32,235); border:2px solid #d42f2f; border-radius:8px; }"
            "QLabel { color:#dbe4f3; background:transparent; font-weight:600; font-size:17px; }"
            "QProgressBar { border:1px solid #22324f; border-radius:4px; background:#0a1120; height:18px; }"
            "QProgressBar::chunk { background:#3ddc97; }")
        g = QGridLayout(self)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        title = QLabel("● TRANSMITTING")
        title.setStyleSheet("color:#ff5a5a; font-weight:700; font-size:19px; background:transparent;")
        g.addWidget(title, 0, 0, 1, 2)
        self._clock = QLabel("00:00.0")
        self._clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clock.setStyleSheet("color:#dbe4f3; font-weight:700; font-size:19px; background:transparent;")
        g.addWidget(self._clock, 0, 2)
        self._t0 = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._show_elapsed)
        self._bars: dict[str, QProgressBar] = {}
        self._vals: dict[str, QLabel] = {}
        for row, name in enumerate(("PWR", "SWR", "ALC"), start=1):
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setMinimumWidth(240)
            val = QLabel("-")
            val.setMinimumWidth(90)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            g.addWidget(QLabel(name), row, 0)
            g.addWidget(bar, row, 1)
            g.addWidget(val, row, 2)
            self._bars[name], self._vals[name] = bar, val
        self._scale = self.POWER_SCALES[0]
        self.hide()

    def _color(self, name: str, color: str) -> None:
        bar = self._bars[name]
        if bar.property("chunk") != color:
            bar.setProperty("chunk", color)
            bar.setStyleSheet("QProgressBar::chunk { background:%s; border-radius:3px; }" % color)

    def _show_elapsed(self) -> None:
        t = max(0.0, time.monotonic() - self._t0)
        self._clock.setText("%02d:%04.1f" % (t // 60, t % 60))

    def begin(self) -> None:
        self._t0 = time.monotonic()
        self._show_elapsed()
        self._tick.start()
        self._scale = self.POWER_SCALES[0]
        self.update_values(0.0, 1.0, 0.0)
        self.show()
        self.raise_()
        self.reposition()

    def end(self) -> None:
        self._tick.stop()
        self.hide()

    def reposition(self, anchor: QWidget | None = None) -> None:
        """Bottom right corner of ``anchor`` (the spectrum area) or, without one, of the parent."""
        p = self.parentWidget()
        if p is None:
            return
        self.adjustSize()
        a = anchor if anchor is not None and anchor.isVisible() else None
        if a is not None:
            r = a.rect().translated(a.mapTo(p, a.rect().topLeft()))
        else:
            r = p.rect()
        self.move(max(0, r.right() - self.width() - 14), max(0, r.bottom() - self.height() - 14))

    def update_values(self, power: float, swr: float, alc: float) -> None:
        while power > self._scale * 0.9 and self._scale < self.POWER_SCALES[-1]:
            self._scale = next(s for s in self.POWER_SCALES if s > self._scale)       # grow only, so it does not jump
        self._bars["PWR"].setValue(int(min(1.0, power / self._scale) * 1000))
        self._vals["PWR"].setText("%.1f W" % power)
        self._bars["SWR"].setValue(int(min(1.0, max(0.0, swr - 1.0) / (self.SWR_MAX - 1.0)) * 1000))
        self._vals["SWR"].setText("%.2f" % swr)
        self._bars["ALC"].setValue(int(min(1.0, alc / self.ALC_MAX) * 1000))
        self._vals["ALC"].setText("%.1f" % alc)
        if swr >= self.SWR_RED:
            swr_col = self.COL_RED
        elif swr > self.SWR_WARN:
            swr_col = self.COL_AMBER
        else:
            swr_col = self.COL_SWR_OK
        self._color("PWR", self.COL_PWR)
        self._color("SWR", swr_col)
        self._color("ALC", self.COL_ALC)
        self._vals["SWR"].setStyleSheet("color:%s; font-weight:700; font-size:17px; background:transparent;" % swr_col)
