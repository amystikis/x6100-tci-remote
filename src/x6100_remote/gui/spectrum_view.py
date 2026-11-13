"""Spectrum trace + scrolling waterfall. Click to tune, mouse wheel to step."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..panelinfo import PLAN_CW, PLAN_DIGITAL, PLAN_PHONE, PlanSegment, Spot
from ..spectrum import SpectrumFrame

AXIS_H = 18
PLAN_H = 4
SPOT_LANES = 3
SPOT_LANE_H = 13
PLAN_COLORS = {PLAN_CW: "#3b82f6", PLAN_DIGITAL: "#a855f7", PLAN_PHONE: "#22c55e"}
PLAN_OTHER_COLOR = "#64748b"
SPOT_COLORS = {"CW": "#f0a830", "SSB": "#4cc9f0"}
TICK_STEPS = (500, 1000, 2000, 2500, 5000, 10_000, 20_000, 50_000, 100_000, 250_000, 500_000)


def make_lut() -> np.ndarray:
    """256-entry colour map (dark blue -> blue -> cyan -> yellow -> red) as 0xFFRRGGBB values."""
    stops = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    rgb = np.array([(2, 6, 28), (8, 48, 168), (0, 200, 210), (245, 225, 50), (255, 70, 30)], dtype=float)
    x = np.linspace(0, 1, 256)
    ch = [np.interp(x, stops, rgb[:, i]).astype(np.uint32) for i in range(3)]
    return (0xFF000000 | (ch[0] << 16) | (ch[1] << 8) | ch[2]).astype(np.uint32)


def nice_step(span_hz: float, target_ticks: int = 8) -> int:
    for s in TICK_STEPS:
        if span_hz / s <= target_ticks:
            return s
    return TICK_STEPS[-1]


class Leveler:
    """Auto-scaling of the radio's uncalibrated bin values to 0..1 (the radio's page does the same)."""

    def __init__(self, alpha: float = 0.08) -> None:
        self.alpha = alpha
        self.lo = self.hi = None

    def update(self, bins: np.ndarray) -> np.ndarray:
        lo = float(np.percentile(bins, 5)) - 4.0
        hi = max(float(np.percentile(bins, 99.5)) + 4.0, lo + 40.0)
        if self.lo is None:
            self.lo, self.hi = lo, hi
        else:
            self.lo += self.alpha * (lo - self.lo)
            self.hi += self.alpha * (hi - self.hi)
        return np.clip((bins.astype(np.float32) - self.lo) / (self.hi - self.lo), 0.0, 1.0)


class SpectrumView(QWidget):
    tune_to = Signal(int)            # absolute Hz that was clicked
    step = Signal(int)               # +1 / -1 for a wheel notch

    def __init__(self, rows: int = 240) -> None:
        super().__init__()
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._lut = make_lut()
        self._bg = int(self._lut[0])
        self._rows = rows
        self._wf: np.ndarray | None = None          # (rows, nbins) uint32 colours
        self._level: np.ndarray | None = None
        self._frame: SpectrumFrame | None = None
        self._leveler = Leveler()
        self._passband: tuple[int, int] | None = None
        self._hover: float | None = None
        self._message = "No spectrum"
        self.frames = 0
        self._plan: list[PlanSegment] = []
        self._spots: list[Spot] = []
        self.show_spots = True
        self._spot_boxes: list[tuple[QRectF, Spot]] = []

    # data --------------------------------------------------------------------------------------
    def set_message(self, text: str) -> None:
        self._message = text
        if self._frame is None:
            self.update()

    def set_passband(self, lo: int, hi: int) -> None:
        """Receive passband as offsets (Hz) from the carrier/VFO."""
        self._passband = (lo, hi)
        self.update()

    def set_plan(self, plan: list[PlanSegment]) -> None:
        self._plan = list(plan)
        self.update()

    def set_spots(self, spots: list[Spot]) -> None:
        self._spots = list(spots)
        self.update()

    def set_show_spots(self, on: bool) -> None:
        self.show_spots = on
        self.update()

    def spot_at(self, x: float, y: float) -> Spot | None:
        if not self.show_spots:
            return None
        for box, spot in self._spot_boxes:
            if box.adjusted(-2, -1, 2, 1).contains(x, y):
                return spot
        return None

    def clear(self) -> None:
        self._frame = self._wf = self._level = None
        self._leveler = Leveler()
        self.update()

    def push(self, frame: SpectrumFrame) -> None:
        n = len(frame.bins)
        old = self._frame
        if self._wf is None or self._wf.shape[1] != n:
            self._wf = np.full((self._rows, n), self._bg, dtype=np.uint32)
        elif old is not None and (old.center_hz != frame.center_hz or old.span_hz != frame.span_hz):
            self._shift_waterfall(old, frame)
        level = self._leveler.update(frame.bins)
        row = self._lut[(level * 255).astype(np.uint8)]
        self._wf[1:] = self._wf[:-1].copy()
        self._wf[0] = row
        self._level, self._frame = level, frame
        self.frames += 1
        self.update()

    def _shift_waterfall(self, old: SpectrumFrame, new: SpectrumFrame) -> None:
        """The radio re-centres on the VFO: slide the history so signals stay where they are."""
        n = self._wf.shape[1]
        d = round((new.center_hz - old.center_hz) / new.hz_per_bin)
        if old.span_hz != new.span_hz or abs(d) >= n:
            self._wf[:] = self._bg
        elif d > 0:
            self._wf[:, :-d] = self._wf[:, d:].copy()
            self._wf[:, -d:] = self._bg
        elif d < 0:
            self._wf[:, -d:] = self._wf[:, :d].copy()
            self._wf[:, :-d] = self._bg

    # geometry ------------------------------------------------------------------------------------
    def _plot_h(self) -> int:
        return max(60, int((self.height() - AXIS_H) * 0.38))

    def _hz_at(self, x: float) -> float | None:
        f = self._frame
        if f is None or self.width() <= 0:
            return None
        return f.center_hz + (x / self.width() - 0.5) * f.span_hz

    def _x_of(self, hz: float) -> float:
        f = self._frame
        return (hz - f.center_hz) / f.span_hz * self.width() + self.width() / 2

    # input ---------------------------------------------------------------------------------------
    def mouseMoveEvent(self, e) -> None:
        self._hover = e.position().x()
        spot = self.spot_at(e.position().x(), e.position().y())
        self.setToolTip(spot.describe() if spot else "")
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        spot = self.spot_at(e.position().x(), e.position().y())
        if spot is not None:
            self.tune_to.emit(spot.freq)                     # exact spot frequency
            return
        hz = self._hz_at(e.position().x())
        if hz is not None:
            self.tune_to.emit(int(round(hz / 10.0)) * 10)

    def wheelEvent(self, e) -> None:
        dy = e.angleDelta().y()
        if dy:
            self.step.emit(1 if dy > 0 else -1)
            e.accept()

    # painting --------------------------------------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#050a14"))
        f = self._frame
        if f is None or self._level is None:
            p.setPen(QColor("#6f819f"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return
        ph = self._plot_h()
        self._paint_trace(p, f, w, ph)
        self._paint_axis(p, f, w, ph)
        self._paint_plan(p, f, w, ph)
        self._paint_spots(p, f, w, ph)
        self._paint_waterfall(p, w, ph + AXIS_H, h - ph - AXIS_H)
        self._paint_markers(p, f, w, h)
        p.end()

    def _paint_trace(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        p.setPen(QPen(QColor("#142238"), 1))
        for i in range(1, 4):
            y = ph * i / 4
            p.drawLine(0, int(y), w, int(y))
        n = len(self._level)
        xs = np.linspace(0, w, w if w < n else n)
        ys = np.interp(xs, np.linspace(0, w, n), self._level)
        pts = [QPointF(0, ph)] + [QPointF(float(x), float(ph - 2 - y * (ph - 6))) for x, y in zip(xs, ys, strict=True)]
        pts.append(QPointF(w, ph))
        fill = QColor("#3ddc97")
        fill.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPolygon(QPolygonF(pts))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#3ddc97"), 1.2))
        p.drawPolyline(QPolygonF(pts[1:-1]))

    def _paint_axis(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        p.fillRect(0, ph, w, AXIS_H, QColor("#0b1220"))
        font = QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        step = nice_step(f.span_hz)
        lo = f.center_hz - f.span_hz / 2
        hz = int(np.ceil(lo / step) * step)
        while hz <= f.center_hz + f.span_hz / 2:
            x = self._x_of(hz)
            p.setPen(QPen(QColor("#22324f"), 1))
            p.drawLine(int(x), 0, int(x), ph + 4)
            p.setPen(QColor("#8ea0bd"))
            label = "%.3f" % (hz / 1e6)
            lx = min(max(x, 34.0), w - 34.0)
            p.drawText(QRectF(lx - 34, ph + 2, 68, AXIS_H - 2), Qt.AlignmentFlag.AlignCenter, label)
            hz += step

    def _paint_plan(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        lo, hi = f.center_hz - f.span_hz / 2, f.center_hz + f.span_hz / 2
        y = ph + AXIS_H - PLAN_H
        for seg in self._plan:
            if seg.hi < lo or seg.lo > hi:
                continue
            x1, x2 = self._x_of(max(seg.lo, lo)), self._x_of(min(seg.hi, hi))
            p.fillRect(QRectF(x1, y, max(1.0, x2 - x1), PLAN_H), QColor(PLAN_COLORS.get(seg.kind, PLAN_OTHER_COLOR)))

    def _paint_spots(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        self._spot_boxes = []
        if not self.show_spots or not self._spots:
            return
        lo, hi = f.center_hz - f.span_hz / 2, f.center_hz + f.span_hz / 2
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        fm = QFontMetricsF(font)
        lane_end = [-1e9] * SPOT_LANES
        for spot in sorted((s for s in self._spots if lo <= s.freq <= hi), key=lambda s: (s.age, s.freq)):
            x = self._x_of(spot.freq)
            tw = fm.horizontalAdvance(spot.call) + 6
            left = min(max(x - tw / 2, 1.0), w - tw - 1)
            lane = next((i for i in range(SPOT_LANES) if left > lane_end[i] + 2), None)
            if lane is None:
                continue                                       # no room, skip rather than overlap
            lane_end[lane] = left + tw
            box = QRectF(left, 2 + lane * SPOT_LANE_H, tw, SPOT_LANE_H - 1)
            color = QColor(SPOT_COLORS.get(spot.mode.upper(), "#a0a8b8"))
            color.setAlpha(255 if spot.age <= 20 else 140)
            stem = QColor(color)
            stem.setAlpha(110)
            p.setPen(QPen(stem, 1))
            p.drawLine(int(x), int(box.bottom()), int(x), ph)
            p.fillRect(box, QColor(5, 10, 20, 215))
            p.setPen(QPen(QColor("#ffffff") if spot.alert else color, 1))
            p.drawRect(box)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, spot.call)
            self._spot_boxes.append((box, spot))

    def _paint_waterfall(self, p: QPainter, w: int, top: int, height: int) -> None:
        if height <= 0 or self._wf is None:
            return
        rows, n = self._wf.shape
        img = QImage(self._wf.data, n, rows, n * 4, QImage.Format.Format_ARGB32)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, top, w, height), img)

    def _paint_markers(self, p: QPainter, f: SpectrumFrame, w: int, h: int) -> None:
        if self._passband is not None:
            lo, hi = sorted(self._passband)
            x1, x2 = self._x_of(f.center_hz + lo), self._x_of(f.center_hz + hi)
            band = QColor("#f0a830")
            band.setAlpha(45)
            p.fillRect(QRectF(x1, 0, max(2.0, x2 - x1), h), band)
        p.setPen(QPen(QColor("#f0a830"), 1.4))
        p.drawLine(int(w / 2), 0, int(w / 2), h)
        if self._hover is not None:
            hz = self._hz_at(self._hover)
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DotLine))
            p.drawLine(int(self._hover), 0, int(self._hover), h)
            text = "%.3f kHz" % (hz / 1000.0)
            tx = min(max(2, self._hover + 6), w - 90)
            p.fillRect(QRectF(tx - 2, 2, 84, 16), QColor(5, 10, 20, 200))
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(tx, 2, 82, 16), Qt.AlignmentFlag.AlignVCenter, text)
