"""Custom-painted widgets: frequency display and S-meter."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

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
