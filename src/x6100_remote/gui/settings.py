"""Persistent settings (saved radios, band memory, window state) via QSettings."""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings

DEFAULT_PORT = 50001
PANEL_PORT = 50002


def qsettings() -> QSettings:
    return QSettings("x6100-tci-remote", "x6100-tci-remote")


def parse_target(text: str) -> str:
    """'192.168.0.150' -> ws://192.168.0.150:50001/ ; also accepts host:port and ws:// URLs."""
    t = text.strip()
    if t.startswith(("ws://", "wss://")):
        return t if t.endswith("/") or "/" in t.split("://", 1)[1] else t + "/"
    host, sep, port = t.partition(":")
    return "ws://%s:%s/" % (host, port if sep and port.isdigit() else DEFAULT_PORT)


def panel_url_for(tci_url: str, port: int = PANEL_PORT) -> str:
    """The spectrum (panel) server runs on the same host as TCI: ws://host:50001/ -> ws://host:50002/."""
    scheme, _, rest = tci_url.partition("://")
    host = rest.split("/", 1)[0].rsplit(":", 1)[0] if ":" in rest.split("/", 1)[0] else rest.split("/", 1)[0]
    return "%s://%s:%d/" % (scheme, host, port)


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


def load_show_spectrum() -> bool:
    return str(qsettings().value("show_spectrum", "true")).lower() != "false"


def save_show_spectrum(on: bool) -> None:
    qsettings().setValue("show_spectrum", "true" if on else "false")


def _host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]


def load_panel_token(url: str) -> str:
    """Pairing key for the radio's panel server (kept per radio, in this user's config only)."""
    try:
        return str(dict(json.loads(qsettings().value("panel_tokens", "{}"))).get(_host_of(url), ""))
    except (ValueError, TypeError):
        return ""


def save_panel_token(url: str, token: str) -> None:
    try:
        tokens = dict(json.loads(qsettings().value("panel_tokens", "{}")))
    except (ValueError, TypeError):
        tokens = {}
    tokens[_host_of(url)] = token
    qsettings().setValue("panel_tokens", json.dumps(tokens))
