"""TCI text protocol: commands look like ``name:arg1,arg2;`` and several may share one
WebSocket text frame. Booleans are ``true``/``false``."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...] = ()

    def __str__(self) -> str:
        return format_command(self.name, *self.args)

    # typed accessors -------------------------------------------------
    def int(self, i: int, default: int = 0) -> int:
        try:
            return int(float(self.args[i]))
        except (IndexError, ValueError):
            return default

    def float(self, i: int, default: float = 0.0) -> float:
        try:
            return float(self.args[i])
        except (IndexError, ValueError):
            return default

    def bool(self, i: int, default: bool = False) -> bool:
        try:
            return self.args[i].strip().lower() == "true"
        except IndexError:
            return default

    def str(self, i: int, default: str = "") -> str:
        try:
            return self.args[i]
        except IndexError:
            return default


def parse_commands(text: str) -> list[Command]:
    """Split one text frame into commands. Unknown/empty fragments are skipped."""
    out: list[Command] = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, sep, rest = chunk.partition(":")
        args = tuple(a.strip() for a in rest.split(",")) if sep else ()
        out.append(Command(name.strip().lower(), args))
    return out


def _fmt(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return ("%g" % v)
    return str(v)


def format_command(name: str, *args: object) -> str:
    if not args:
        return f"{name};"
    return f"{name}:{','.join(_fmt(a) for a in args)};"


# S-meter helpers ------------------------------------------------------------
S9_DBM = -73.0          # IARU HF convention: S9 = -73 dBm, 6 dB per S-unit


def dbm_to_s(dbm: float) -> tuple[str, float]:
    """Return (label, fraction 0..1 of the scale S1..S9+60). e.g. -73 -> ('S9', 0.6)."""
    if dbm >= S9_DBM:
        over = dbm - S9_DBM
        label = "S9" if over < 5 else "S9+%d" % (round(over / 10) * 10)
        frac = 0.6 + min(over, 60.0) / 60.0 * 0.4
    else:
        s = max(1.0, 9.0 + (dbm - S9_DBM) / 6.0)
        label = "S%d" % round(s)
        frac = (s - 1.0) / 8.0 * 0.6
    return label, max(0.0, min(1.0, frac))
