"""CW tuner: offset estimate from spectrum bins, widget behaviour, mode wiring."""
import os

import numpy as np
import pytest

from x6100_remote.cwtuner import CwTune, analyze, smooth, window_half_width, window_levels
from x6100_remote.spectrum import SpectrumFrame

N, SPAN, CENTRE = 1024, 100_000, 7_030_000
HZ_BIN = SPAN / N


def frame_with(peaks: dict[float, float], noise: float = 140.0, seed: int = 1) -> SpectrumFrame:
    """Frame with Gaussian-ish peaks at given offsets (Hz from the centre) and heights (raw units)."""
    rng = np.random.default_rng(seed)
    x = np.arange(N)
    bins = noise + rng.normal(0, 1.0, N)
    for off, h in peaks.items():
        bins += h * np.exp(-(((x - (N / 2 + off / HZ_BIN)) / 1.2) ** 2))
    return SpectrumFrame(CENTRE, SPAN, 1, np.clip(bins, 0, 255).astype(np.uint8))


def test_offset_estimate_follows_the_peak():
    for off in (-250.0, -120.0, 0.0, 48.0, 100.0, 233.0):
        t = analyze(frame_with({off: 50}), bandwidth_hz=500)
        assert t is not None
        assert abs(t.offset_hz - off) < 30, (off, t.offset_hz)          # within a third of a ~98 Hz bin


def test_alignment_and_passband_flags():
    on = analyze(frame_with({3.0: 60}), 500)
    assert on.aligned and on.in_passband
    near = analyze(frame_with({150.0: 60}), 500)
    assert not near.aligned and near.in_passband
    far = analyze(frame_with({380.0: 60}), 200, half_window_hz=500)      # outside a 200 Hz passband (+-100)
    assert far is not None and not far.in_passband


def test_no_signal_returns_none():
    assert analyze(frame_with({}), 500) is None
    assert analyze(frame_with({0.0: 4}), 500) is None                    # a bump below the threshold


def test_ignores_signals_outside_the_window():
    assert analyze(frame_with({5_000.0: 80}), 500) is None


def test_window_levels_and_half_width():
    f = frame_with({0.0: 60})
    lv = window_levels(f, 400, 21)
    assert len(lv) == 21 and lv.argmax() in (10, 11, 9) and lv.max() > lv.min() + 30
    assert window_half_width(500) == 400 and window_half_width(100) == 300


def test_smoothing_reduces_jitter_and_restarts_on_a_new_station():
    rng = np.random.default_rng(3)
    raw, sm, prev = [], [], None
    for _ in range(200):
        t = analyze(frame_with({70.0: 34}, seed=int(rng.integers(1 << 30))), 700)
        raw.append(t.offset_hz)
        prev = smooth(prev, t, 700)
        sm.append(prev.offset_hz)
    assert np.std(sm[20:]) < 0.6 * np.std(raw[20:]) and abs(np.mean(sm[20:]) - 70) < 8
    a = CwTune(70.0, 30.0, True, False)
    assert smooth(a, CwTune(-300.0, 30.0, True, False), 700).offset_hz == -300.0   # another station: no blending
    assert smooth(a, None, 700) is None and smooth(None, a, 700) is a


# ---- GUI ---------------------------------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_widget_draws_tuner_only_when_enabled():
    from PySide6.QtWidgets import QApplication

    from x6100_remote.gui.spectrum_view import SpectrumView
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=8)
    v.resize(800, 500)
    v.push(frame_with({60.0: 60}))
    assert v._cw_tune is None                                            # not in a CW mode
    v.set_cw_tuner(500)
    assert v._cw_tune is not None and abs(v._cw_tune.offset_hz - 60) < 30
    v.grab()                                                             # paints with bars and label
    v.push(frame_with({}))
    assert v._cw_tune is not None and v._cw_shown is not None            # keyed CW: the reading is held for a while
    v.grab()
    v._cw_seen -= 5.0                                                    # ... then dropped
    v.push(frame_with({}))
    assert v._cw_tune is None and v._cw_shown is None
    v.grab()                                                             # "no signal" label
    v.set_show_cw_tuner(False)
    v.set_cw_tuner(None)
    assert v._cw_tune is None
    v.grab()


def test_meter_sits_top_left_of_the_vfo_line_and_spots_keep_clear():
    from PySide6.QtWidgets import QApplication

    from x6100_remote.gui.spectrum_view import SpectrumView
    from x6100_remote.panelinfo import Spot
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=8)
    v.resize(800, 500)
    v.push(frame_with({60.0: 60}))
    v.set_cw_tuner(500)
    r = v._cw_meter_rect(800)
    assert r.right() <= 400 and r.top() < 10 and r.left() > 0               # left of the line, at the top
    spots = [Spot(CENTRE + off, "S%d" % i, "CW") for i, off in enumerate((-9000, -7000, -4000, -2000, 3000, 9000))]
    v.set_spots(spots)
    v.grab()
    drawn = {s.call for _, s in v._spot_boxes}
    assert drawn                                                             # spots are still shown
    assert not any(box.intersects(r) for box, _ in v._spot_boxes)           # none under the meter
    v.set_cw_tuner(None)
    v.grab()
    assert len(v._spot_boxes) >= len(drawn)                                  # all back when the meter is off


ALIGN_TOL = 20.0


def test_signal_at_the_cw_pitch_is_on_tone_and_cwr_mirrors():
    from x6100_remote.cwtuner import target_hz
    assert target_hz("cw", 600) == 600 and target_hz("cwr", 600) == -600
    t = analyze(frame_with({600.0: 60}), 500, target_hz=600)
    assert t is not None and t.aligned and abs(t.offset_hz) < ALIGN_TOL
    t = analyze(frame_with({-600.0: 60}), 500, target_hz=-600)
    assert t is not None and t.aligned
    off = analyze(frame_with({650.0: 60}), 500, target_hz=600)
    assert off is not None and 20 < off.offset_hz < 80 and not off.aligned          # 50 Hz high of the tone
    # a signal on the VFO line is NOT on tone any more when the pitch is 600
    on_line = analyze(frame_with({0.0: 60}), 500, target_hz=600)
    assert on_line is None or not on_line.aligned


def test_reading_is_steady_and_bars_hold():
    from PySide6.QtWidgets import QApplication

    from x6100_remote.gui.spectrum_view import SpectrumView
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=8)
    v.resize(800, 500)
    v.push(frame_with({60.0: 60}))
    v.set_cw_tuner(500)
    shown = [v._cw_shown]
    for i in range(20):                                                  # 20 quick frames: readout is not refreshed
        v.push(frame_with({60.0 + (i % 2) * 40: 60}, seed=i))            # each frame (rate limited), so it holds still
    assert v._cw_shown is shown[0] or abs(v._cw_shown.offset_hz - shown[0].offset_hz) < 40
    v.grab()
    peak = v._cw_hold.max()
    v.push(frame_with({}))
    v.grab()
    assert v._cw_hold.max() > 0.8 * peak                                 # bars fall slowly, not instantly


def test_3d_waterfall_styles_paint_and_follow_zoom():
    from PySide6.QtWidgets import QApplication

    from x6100_remote.gui.spectrum_view import WF_STYLES, SpectrumView
    QApplication.instance() or QApplication([])
    v = SpectrumView(rows=60)
    v.resize(800, 500)
    for i in range(30):
        v.push(frame_with({60.0: 60}, seed=i))
    for style in WF_STYLES:
        v.set_waterfall_style(style)
        assert v._wf_style == style
        v.grab()
        v.set_zoom(4)
        v.grab()
        v.set_zoom(1)
    v.set_waterfall_style("ridges")                                      # an older saved name maps to the 3D style
    assert v._wf_style == "3d"
    v.grab()
    assert v._wf3d_img is not None and v._wf3d_img.width() == 800
    img, t = v._wf3d_img, v._wf3d_t
    v.push(frame_with({60.0: 60}, seed=99))
    v.grab()                                                             # inside the redraw interval: cache is reused
    assert v._wf3d_img is img and v._wf3d_t == t
    v.set_waterfall_style("nonsense")
    assert v._wf_style == "2d"
