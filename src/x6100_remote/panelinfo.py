"""Text messages of the OpenX6X00 panel server (port 50002) that describe the radio, not the RF.

Observed on a real radio (firmware v0.3.9). One message per text frame, ``<kind> <payload>``::

    hello OpenX6X00 - v0.3.9 1728545579
    bands [{"n":"160m","a":1810000,"b":2000000}, ...]            band list (name, low Hz, high Hz)
    plan  [[1810000,1838000,0], ...]                              band plan segments [low, high, kind]
    spots [{"f":7043000,"c":"AC4WW","m":"CW","a":0,"s":"WB6BEE-#","k":"POTA US-9774 CW","al":0}, ...]
    state {"freq":7174000,"mode":0,"flo":50,"fhi":3050,"pre":1,"att":0,"nb":0,"nr":0,"sql":0,"rfg":70,
           "vol":0,"pwr":2.5,"step":500,"zoom":4,"atu":0,"bat":-1,"tx":0,"lock":0, ...}
    ft8   {"open":0,"tx":0,"cq":0,"auto":0,"next":"","logged":"", ...}
    cw    "TTM "                                                  text decoded by the radio (JSON string)

``bands``, ``plan`` and ``state`` arrive on connect, ``spots`` about every 15 s. The meaning of the plan kinds
(0 CW, 1 digital/narrow, 2 phone, 3 other) is inferred from the IARU segments of 160 m; the spot age ``a`` looks like
minutes (0-29); ``bat`` is -1 when unknown. Anything not understood is kept as is and otherwise ignored.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

PLAN_CW, PLAN_DIGITAL, PLAN_PHONE, PLAN_OTHER = 0, 1, 2, 3
CW_HISTORY_MAX = 4000


@dataclass
class Spot:
    freq: int
    call: str
    mode: str = ""
    age: int = 0                  # minutes (inferred)
    spotter: str = ""
    comment: str = ""
    alert: bool = False

    def describe(self) -> str:
        bits = ["%s  %s  %.1f kHz" % (self.call, self.mode, self.freq / 1000)]
        if self.comment:
            bits.append(self.comment)
        if self.spotter:
            bits.append("spotted by %s, %d min ago" % (self.spotter, self.age))
        return "\n".join(bits)


@dataclass
class PlanSegment:
    lo: int
    hi: int
    kind: int


@dataclass
class BandInfo:
    name: str
    lo: int
    hi: int


def merge_cw(history: str, new: str) -> str:
    """Add a message of the radio's CW decoder to the history.

    It is not known whether the radio sends increments or its whole buffer, so this handles both: a message that
    extends the history (or sits inside it) does not duplicate text; anything else is appended."""
    if not history:
        return new
    if new in history[-len(new) - 8:] and len(new) >= 3:
        return history
    for k in range(min(len(history), len(new)), 0, -1):
        if history.endswith(new[:k]) and (k >= 4 or k == len(history)):
            return (history + new[k:])[-CW_HISTORY_MAX:]
    return (history + new)[-CW_HISTORY_MAX:]


@dataclass
class PanelInfo:
    hello: str = ""
    bands: list[BandInfo] = field(default_factory=list)
    plan: list[PlanSegment] = field(default_factory=list)
    spots: list[Spot] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    ft8: dict[str, Any] = field(default_factory=dict)
    cw_text: str = ""
    volmax: int = 0
    pwrmax: int = 0
    role: str = "view"            # "view" until this app is paired; then "operate" or "admin"
    tx_allowed: bool = False      # the radio's per-device "may transmit" flag
    role_name: str = ""
    ctl_who: str = ""

    def apply(self, line: str) -> Optional[str]:
        """Update from one text line; return what changed (``"bands"``, ``"spots"``, ...) or None."""
        kind, _, payload = line.partition(" ")
        try:
            if kind == "hello":
                self.hello = payload
            elif kind == "bands":
                self.bands = [BandInfo(str(b["n"]), int(b["a"]), int(b["b"])) for b in json.loads(payload)]
            elif kind == "plan":
                self.plan = [PlanSegment(int(s[0]), int(s[1]), int(s[2])) for s in json.loads(payload)]
            elif kind == "spots":
                self.spots = [Spot(int(s["f"]), str(s.get("c", "")), str(s.get("m", "")), int(s.get("a", 0)),
                                   str(s.get("s", "")), str(s.get("k", "")), bool(s.get("al", 0)))
                              for s in json.loads(payload)]
            elif kind == "state":
                self.state.update(json.loads(payload))
            elif kind == "ft8":
                self.ft8 = dict(json.loads(payload))
            elif kind == "cw":
                self.cw_text = merge_cw(self.cw_text, str(json.loads(payload)))
            elif kind == "role":
                parts = payload.split()
                self.role = parts[0]
                self.tx_allowed = len(parts) > 1 and parts[1] == "1"
                self.role_name = " ".join(parts[2:]).replace("-", "", 1) if len(parts) > 2 else ""
            elif kind == "ctl":
                self.ctl_who = payload.split()[0] if payload.split() else ""
            elif kind == "volmax":
                self.volmax = int(payload)
            elif kind == "pwrmax":
                self.pwrmax = int(payload)
            else:
                return None
        except (ValueError, KeyError, TypeError, IndexError):
            return None
        return kind

    # convenience ------------------------------------------------------------------------------
    def spots_in(self, lo: float, hi: float) -> list[Spot]:
        return [s for s in self.spots if lo <= s.freq <= hi]

    @property
    def battery(self) -> Optional[int]:
        b = self.state.get("bat", -1)
        return int(b) if isinstance(b, (int, float)) and b >= 0 else None

    def status_items(self) -> list[tuple[str, str, bool]]:
        """(label, value, highlighted) for the status strip, only for fields the radio reported."""
        s = self.state
        items: list[tuple[str, str, bool]] = []

        def add(label: str, key: str, fmt=None, zero_off: bool = True):
            if key not in s:
                return
            v = s[key]
            on = bool(v)
            items.append((label, "off" if (zero_off and not on) else (fmt(v) if fmt else str(v)), on))

        add("PRE", "pre")
        add("ATT", "att")
        add("NB", "nb")
        add("NR", "nr")
        add("SQL", "sql")
        add("RFG", "rfg", zero_off=False)
        add("PWR", "pwr", lambda v: "%g W" % v, zero_off=False)
        add("ATU", "atu")
        if self.battery is not None:
            items.append(("BAT", "%d%%" % self.battery, self.battery < 20))
        return items
