"""Spectrum trace + scrolling waterfall. Click to tune, mouse wheel to step."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..cwtuner import (BAR_FALL_PER_S, HOLD_S, SHOWN_EVERY_S, SMOOTH_ALPHA, CwTune, analyze, smooth,
                       window_half_width, window_levels)
from ..panelinfo import PLAN_CW, PLAN_DIGITAL, PLAN_PHONE, PlanSegment, Spot
from ..spectrum import SpectrumFrame

AXIS_H = 18
PLAN_H = 14                     # band-plan strip under the frequency axis (holds the labels)
SPOT_LANES = 3
SPOT_LANE_H = 13
PLAN_COLORS = {PLAN_CW: "#3b82f6", PLAN_DIGITAL: "#a855f7", PLAN_PHONE: "#22c55e"}
PLAN_OTHER_COLOR = "#64748b"
PLAN_LABELS = {
    PLAN_CW: ("CW",),
    PLAN_DIGITAL: ("DIGITAL", "DIGI", "DG"),
    PLAN_PHONE: ("ALL MODES / SSB", "ALL / SSB", "SSB", "PH"),
}
PLAN_OTHER_LABELS = ("OTHER", "OTH")
SPOT_COLORS = {"CW": "#f0a830", "SSB": "#4cc9f0"}
TICK_STEPS = (500, 1000, 2000, 2500, 5000, 10_000, 20_000, 50_000, 100_000, 250_000, 500_000)


WATERFALL_SCHEMES: dict[str, list[tuple[int, int, int]]] = {       # 5 evenly spaced colour stops, weak -> strong
    "Classic": [(2, 6, 28), (8, 48, 168), (0, 200, 210), (245, 225, 50), (255, 70, 30)],
    "Inferno": [(0, 0, 4), (87, 16, 110), (188, 55, 84), (249, 142, 9), (252, 255, 164)],
    "Viridis": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "Grayscale": [(0, 0, 0), (64, 64, 64), (128, 128, 128), (192, 192, 192), (255, 255, 255)],
    "Green phosphor": [(0, 8, 0), (0, 70, 10), (0, 150, 30), (80, 230, 60), (220, 255, 200)],
    "Ice": [(5, 10, 30), (20, 60, 120), (60, 140, 200), (170, 220, 245), (255, 255, 255)],
}
SPECTRUM_SCHEMES: dict[str, str] = {                                   # trace colour
    "Green": "#3ddc97", "Cyan": "#4cc9f0", "Amber": "#f0a830", "White": "#e6edf7", "Magenta": "#e879f9",
}
DEFAULT_WATERFALL = "Classic"
DEFAULT_SPECTRUM = "Green"
ZOOM_LEVELS = (1, 2, 4, 8)


def make_lut(scheme: str = DEFAULT_WATERFALL) -> np.ndarray:
    """256-entry colour map for a waterfall scheme as 0xFFRRGGBB values."""
    stops = np.linspace(0.0, 1.0, 5)
    rgb = np.array(WATERFALL_SCHEMES.get(scheme, WATERFALL_SCHEMES[DEFAULT_WATERFALL]), dtype=float)
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
        self.setMinimumSize(320, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._lut = make_lut()
        self._bg = int(self._lut[0])
        self._rows = rows
        self._wf: np.ndarray | None = None          # (rows, nbins) uint32 colours
        self._wl: np.ndarray | None = None          # (rows, nbins) uint8 levels (so a colour scheme can be swapped)
        self._zoom = 1
        self._trace_color = QColor(SPECTRUM_SCHEMES[DEFAULT_SPECTRUM])
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
        self.show_cw_tuner = True
        self._cw_bw: int | None = None                # passband width (Hz) while in CW/CW-R, else None
        self._cw_tune: CwTune | None = None           # smoothed reading (held for HOLD_S after the signal drops)
        self._cw_seen = 0.0                           # monotonic time of the last frame that had a signal
        self._cw_shown: CwTune | None = None          # what the readout shows (refreshed a few times per second)
        self._cw_shown_t = 0.0
        self._cw_hold: np.ndarray | None = None       # peak-hold bar heights
        self._cw_hold_t = 0.0
        self._cw_target = 0.0
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

    def set_cw_tuner(self, bandwidth_hz: int | None, target_hz: float = 0.0) -> None:
        """Enable the CW tuner indicator: passband width and where the tuned signal should sit relative to the VFO
        (the CW pitch, negative in CW-R). None: not in a CW mode."""
        self._cw_bw = bandwidth_hz
        self._cw_target = float(target_hz)
        self._cw_tune = (analyze(self._frame, bandwidth_hz, target_hz=self._cw_target)
                         if (bandwidth_hz and self._frame) else None)
        self._cw_seen = time.monotonic()
        self._cw_shown, self._cw_hold = self._cw_tune, None
        self.update()

    def set_zoom(self, zoom: int) -> None:
        """Show only the middle 1/zoom of the radio's span (display zoom; the radio's own span is not changed)."""
        self._zoom = zoom if zoom in ZOOM_LEVELS else 1
        self.update()

    def set_waterfall_scheme(self, name: str) -> None:
        self._lut = make_lut(name)
        self._bg = int(self._lut[0])
        if self._wl is not None:
            self._wf = self._lut[self._wl]
        self.update()

    def set_spectrum_scheme(self, name: str) -> None:
        self._trace_color = QColor(SPECTRUM_SCHEMES.get(name, SPECTRUM_SCHEMES[DEFAULT_SPECTRUM]))
        self.update()

    def set_show_cw_tuner(self, on: bool) -> None:
        self.show_cw_tuner = on
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
        self._frame = self._wf = self._wl = self._level = None
        self._leveler = Leveler()
        self.update()

    def push(self, frame: SpectrumFrame) -> None:
        n = len(frame.bins)
        old = self._frame
        if self._wf is None or self._wf.shape[1] != n:
            self._wf = np.full((self._rows, n), self._bg, dtype=np.uint32)
            self._wl = np.zeros((self._rows, n), dtype=np.uint8)
        elif old is not None and (old.center_hz != frame.center_hz or old.span_hz != frame.span_hz):
            self._shift_waterfall(old, frame)
        level = self._leveler.update(frame.bins)
        lv = (level * 255).astype(np.uint8)
        self._wf[1:] = self._wf[:-1].copy()
        self._wl[1:] = self._wl[:-1].copy()
        self._wf[0] = self._lut[lv]
        self._wl[0] = lv
        self._level, self._frame = level, frame
        self._track_cw(frame)
        self.frames += 1
        self.update()

    def _track_cw(self, frame: SpectrumFrame) -> None:
        """Steady CW tuner reading: heavy smoothing, and the last reading is held while keyed CW is between elements."""
        if not self._cw_bw:
            self._cw_tune = self._cw_shown = None
            return
        now = time.monotonic()
        raw = analyze(frame, self._cw_bw, target_hz=self._cw_target)
        if raw is not None:
            self._cw_tune = smooth(self._cw_tune, raw, self._cw_bw, alpha=SMOOTH_ALPHA)
            self._cw_seen = now
        elif now - self._cw_seen > HOLD_S:
            self._cw_tune = None
        if now - self._cw_shown_t >= SHOWN_EVERY_S or (self._cw_tune is None) != (self._cw_shown is None):
            self._cw_shown, self._cw_shown_t = self._cw_tune, now

    def _shift_waterfall(self, old: SpectrumFrame, new: SpectrumFrame) -> None:
        """The radio re-centres on the VFO: slide the history so signals stay where they are."""
        n = self._wf.shape[1]
        d = round((new.center_hz - old.center_hz) / new.hz_per_bin)
        for a, bg in ((self._wf, self._bg), (self._wl, 0)):
            if old.span_hz != new.span_hz or abs(d) >= n:
                a[:] = bg
            elif d > 0:
                a[:, :-d] = a[:, d:].copy()
                a[:, -d:] = bg
            elif d < 0:
                a[:, -d:] = a[:, :d].copy()
                a[:, :-d] = bg

    # geometry ------------------------------------------------------------------------------------
    def _plot_h(self) -> int:
        return max(60, int((self.height() - AXIS_H - PLAN_H) * 0.38))

    def _hz_at(self, x: float) -> float | None:
        f = self._frame
        if f is None or self.width() <= 0:
            return None
        return f.center_hz + (x / self.width() - 0.5) * f.span_hz / self._zoom

    def _x_of(self, hz: float) -> float:
        f = self._frame
        return (hz - f.center_hz) / (f.span_hz / self._zoom) * self.width() + self.width() / 2

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
        self._paint_cw_tuner(p, f, w, ph)
        self._paint_waterfall(p, w, ph + AXIS_H + PLAN_H, h - ph - AXIS_H - PLAN_H)
        self._paint_markers(p, f, w, h)
        p.end()

    def _paint_trace(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        p.setPen(QPen(QColor("#142238"), 1))
        for i in range(1, 4):
            y = ph * i / 4
            p.drawLine(0, int(y), w, int(y))
        n = len(self._level)
        xs = np.linspace(0, w, w if w < n else n)
        ys = np.interp((n - 1) / 2 + (xs / w - 0.5) * (n - 1) / self._zoom, np.arange(n), self._level)
        pts = [QPointF(0, ph)] + [QPointF(float(x), float(ph - 2 - y * (ph - 6))) for x, y in zip(xs, ys, strict=True)]
        pts.append(QPointF(w, ph))
        fill = QColor(self._trace_color)
        fill.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPolygon(QPolygonF(pts))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._trace_color, 1.2))
        p.drawPolyline(QPolygonF(pts[1:-1]))

    def _paint_axis(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        p.fillRect(0, ph, w, AXIS_H, QColor("#0b1220"))
        font = QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        vspan = f.span_hz / self._zoom
        step = nice_step(vspan)
        lo = f.center_hz - vspan / 2
        hz = int(np.ceil(lo / step) * step)
        while hz <= f.center_hz + vspan / 2:
            x = self._x_of(hz)
            p.setPen(QPen(QColor("#22324f"), 1))
            p.drawLine(int(x), 0, int(x), ph + 4)
            p.setPen(QColor("#8ea0bd"))
            label = "%.3f" % (hz / 1e6)
            lx = min(max(x, 34.0), w - 34.0)
            p.drawText(QRectF(lx - 34, ph + 2, 68, AXIS_H - 2), Qt.AlignmentFlag.AlignCenter, label)
            hz += step

    def _paint_plan(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        vspan = f.span_hz / self._zoom
        lo, hi = f.center_hz - vspan / 2, f.center_hz + vspan / 2
        y = ph + AXIS_H
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetricsF(font)
        for seg in self._plan:
            if seg.hi < lo or seg.lo > hi:
                continue
            x1, x2 = self._x_of(max(seg.lo, lo)), self._x_of(min(seg.hi, hi))
            rect = QRectF(x1, y, max(1.0, x2 - x1), PLAN_H)
            p.fillRect(rect, QColor(PLAN_COLORS.get(seg.kind, PLAN_OTHER_COLOR)))
            p.setPen(QPen(QColor("#050a14"), 1))                      # thin separator between neighbouring segments
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.left(), y + PLAN_H))
            labels = PLAN_LABELS.get(seg.kind, PLAN_OTHER_LABELS)
            # label sits in the visible part of the segment; pick the longest text that fits
            vis_l, vis_r = max(rect.left(), 0.0), min(rect.right(), float(w))
            label = next((s for s in labels if fm.horizontalAdvance(s) + 6 <= vis_r - vis_l), None)
            if label:
                p.setPen(QColor("#ffffff"))
                p.drawText(QRectF(vis_l, y, vis_r - vis_l, PLAN_H), Qt.AlignmentFlag.AlignCenter, label)

    def _paint_spots(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        self._spot_boxes = []
        if not self.show_spots or not self._spots:
            return
        vspan = f.span_hz / self._zoom
        lo, hi = f.center_hz - vspan / 2, f.center_hz + vspan / 2
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        fm = QFontMetricsF(font)
        lane_end = [-1e9] * SPOT_LANES
        meter = self._cw_meter_rect(w)
        for spot in sorted((s for s in self._spots if lo <= s.freq <= hi), key=lambda s: (s.age, s.freq)):
            x = self._x_of(spot.freq)
            tw = fm.horizontalAdvance(spot.call) + 6
            left = min(max(x - tw / 2, 1.0), w - tw - 1)

            def lane_box(i: int, left: float = left, tw: float = tw) -> QRectF:
                return QRectF(left, 2 + i * SPOT_LANE_H, tw, SPOT_LANE_H - 1)

            lane = next((i for i in range(SPOT_LANES)
                         if left > lane_end[i] + 2 and not (meter and lane_box(i).intersects(meter))), None)
            if lane is None:
                continue                                       # no room (or under the CW meter): skip, never overlap
            lane_end[lane] = left + tw
            box = lane_box(lane)
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

    CW_BAR_H = 28

    def _cw_meter_rect(self, w: int) -> QRectF | None:
        """The CW tuner meter: top of the scope, its right edge on the VFO line (top-left corner of the line)."""
        if self._cw_bw is None or not self.show_cw_tuner or self._level is None:
            return None
        strip_w = max(110.0, min(230.0, w * 0.3))                  # a fixed-size meter, not tied to the span
        x1 = w / 2 - 3
        return QRectF(x1 - strip_w, 3, strip_w, self.CW_BAR_H + 6)

    def _paint_cw_tuner(self, p: QPainter, f: SpectrumFrame, w: int, ph: int) -> None:
        """Vertical bars centred on the VFO line: the spectrum over the passband (and a bit more), the bar of the
        strongest signal coloured by how well it is aligned, and its offset in Hz."""
        rect = self._cw_meter_rect(w)
        if rect is None:
            return
        bw = float(self._cw_bw)
        half = min(window_half_width(bw), f.span_hz / self._zoom / 2.0)
        n, bar_h = 21, self.CW_BAR_H
        top = rect.top() + 3
        x0, x1 = rect.left(), rect.right()
        p.fillRect(rect, QColor(5, 10, 20, 190))
        levels = np.clip(window_levels(f, half, n, values=self._level, centre_hz=self._cw_target), 0.0, 1.0)
        now = time.monotonic()
        if self._cw_hold is None or len(self._cw_hold) != n:
            self._cw_hold = levels.copy()
        else:                                                      # peak hold: jump up at once, fall slowly
            fall = BAR_FALL_PER_S * min(0.5, now - self._cw_hold_t)
            self._cw_hold = np.maximum(levels, self._cw_hold - fall)
        self._cw_hold_t = now
        levels = self._cw_hold
        bar_w = (x1 - x0) / n
        tune = self._cw_shown
        peak_i = None
        if tune is not None and abs(tune.offset_hz) < half:
            peak_i = min(n - 1, max(0, int((tune.offset_hz + half) / (2 * half) * n)))
        for i, lvl in enumerate(levels):
            offset = -half + (i + 0.5) * (2 * half / n)
            colour = QColor("#f0a830") if abs(offset) <= bw / 2 else QColor("#55637d")
            if i == peak_i:
                colour = QColor("#3ddc97") if tune.aligned else QColor("#ff8a4c" if tune.in_passband else "#ff5a5a")
            h = max(2.0, bar_h * float(lvl))
            p.fillRect(QRectF(x0 + i * bar_w + 1, top + bar_h - h, max(1.0, bar_w - 2), h), colour)
        # label with the offset
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        if tune is None:
            text, colour = "CW  no signal", QColor("#6f819f")
        else:
            text = "%+d Hz%s" % (round(tune.offset_hz), "  on tone" if tune.aligned else "")
            colour = QColor("#3ddc97") if tune.aligned else QColor("#ff8a4c" if tune.in_passband else "#ff5a5a")
        lx = x0 - 112 if x0 - 112 > 0 else x1 + 8                   # label to the left of the meter
        ly = top + bar_h / 2 - 8
        p.fillRect(QRectF(lx, ly, 106, 16), QColor(5, 10, 20, 215))
        p.setPen(colour)
        p.drawText(QRectF(lx, ly, 106, 16), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_waterfall(self, p: QPainter, w: int, top: int, height: int) -> None:
        if height <= 0 or self._wf is None:
            return
        rows, n = self._wf.shape
        img = QImage(self._wf.data, n, rows, n * 4, QImage.Format.Format_ARGB32)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        vis = n / self._zoom
        p.drawImage(QRectF(0, top, w, height), img, QRectF((n - vis) / 2, 0, vis, rows))

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
