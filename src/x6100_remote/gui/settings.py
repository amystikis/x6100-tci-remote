"""Persistent settings (saved radios, band memory, window state) via QSettings."""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings

DEFAULT_PORT = 50001


def qsettings() -> QSettings:
    return QSettings("x6100-tci-remote", "x6100-tci-remote")


def parse_target(text: str) -> str:
    """'192.168.0.150' -> ws://192.168.0.150:50001/ ; also accepts host:port and ws:// URLs."""
    t = text.strip()
    if t.startswith(("ws://", "wss://")):
        return t if t.endswith("/") or "/" in t.split("://", 1)[1] else t + "/"
    host, sep, port = t.partition(":")
    return "ws://%s:%s/" % (host, port if sep and port.isdigit() else DEFAULT_PORT)


def load_radios() -> list[str]:
    try:
        return list(json.loads(qsettings().value("radios", "[]")))
    except (ValueError, TypeError):
        return []


def remember_radio(text: str) -> None:
    radios = [r for r in load_radios() if r != text]
    radios.insert(0, text)
    qsettings().setValue("radios", json.dumps(radios[:12]))


def load_band_memory() -> dict:
    try:
        return dict(json.loads(qsettings().value("band_memory", "{}")))
    except (ValueError, TypeError):
        return {}


def save_band_memory(mem: dict) -> None:
    qsettings().setValue("band_memory", json.dumps(mem))
