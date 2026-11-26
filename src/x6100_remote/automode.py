"""Which mode a frequency should be in: sideband by band, DIGU in digital segments, CW in CW segments.

Rules (the operator's, not a regulation): below 10 MHz (160, 80, 60 and 40 m) voice is LSB, from 10 MHz up it is USB;
a digital segment of the radio's band plan is always DIGU; a CW segment is CW. Anything else (no band, "other"
segments, or a mode like AM/FM that is not a sideband mode) is left alone.
"""
from __future__ import annotations

from typing import Optional, Sequence

from .panelinfo import PLAN_CW, PLAN_DIGITAL, PLAN_PHONE, PlanSegment

LSB_BELOW_HZ = 10_000_000
# modes that already satisfy a wanted mode
EQUIVALENT = {"lsb": {"lsb"}, "usb": {"usb"}, "digu": {"digu"}, "cw": {"cw"}}
# modes the automatic selection may replace; AM, FM and the rest are a deliberate choice and stay as they are
REPLACEABLE = {"lsb", "usb", "cw", "cwr", "digl", "digu"}


def sideband(hz: int) -> str:
    return "lsb" if hz < LSB_BELOW_HZ else "usb"


def desired_mode(hz: int, in_band: bool, plan: Sequence[PlanSegment]) -> Optional[str]:
    """The mode ``hz`` should use, or None when there is no rule for it."""
    if not in_band:
        return None
    seg = next((s for s in plan if s.lo <= hz < s.hi), None)
    if seg is None:                                  # no plan for this part (or none loaded yet): treat it as voice
        return sideband(hz)
    if seg.kind == PLAN_CW:
        return "cw"
    if seg.kind == PLAN_DIGITAL:
        return "digu"
    if seg.kind == PLAN_PHONE:
        return sideband(hz)
    return None


def needs_change(current: str, wanted: Optional[str]) -> bool:
    return wanted is not None and current in REPLACEABLE and current not in EQUIVALENT[wanted]
