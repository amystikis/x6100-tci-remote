"""Colour themes for the whole window (Qt style sheet + the custom-painted widgets).

The spectrum and waterfall keep their own dark "scope" look in every theme (the waterfall colour schemes are made for a
dark background); everything around them follows the theme.
"""
from __future__ import annotations

from dataclasses import dataclass
from string import Template


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str            # window background
    text: str          # normal text
    muted: str         # group titles, info line
    panel: str         # frequency display / S-meter / input background
    edge: str          # borders
    edge2: str         # button and input borders
    btn: str
    btn_hover: str
    btn_off_bg: str    # disabled button
    btn_off_text: str
    accent: str        # frequency digits, checked buttons, sliders
    accent_text: str   # text on an accent background
    green: str
    red: str
    dim: str           # inactive digits, scale marks
    on_bg: str         # a "lit" radio-key button
    on_text: str
    ptt: str
    ptt_edge: str
    ptt_off_bg: str
    ptt_off_edge: str
    meter_bg: str
    peak: str


MIDNIGHT = Theme(
    "Midnight", bg="#0b1220", text="#dbe4f3", muted="#8ea0bd", panel="#0e1626", edge="#22324f", edge2="#2a3a58",
    btn="#1b2a44", btn_hover="#24365a", btn_off_bg="#121c30", btn_off_text="#55637d", accent="#f0a830",
    accent_text="#1a1204", green="#3ddc97", red="#ff5a5a", dim="#5b6b88", on_bg="#1f3d33", on_text="#bff5dc",
    ptt="#5a1f1f", ptt_edge="#8a2d2d", ptt_off_bg="#241618", ptt_off_edge="#3a2326", meter_bg="#0a1120",
    peak="#dbe4f3")

DARK = Theme(
    "Dark", bg="#1e1e1e", text="#e2e2e2", muted="#a0a0a0", panel="#262626", edge="#3c3c3c", edge2="#4a4a4a",
    btn="#333333", btn_hover="#424242", btn_off_bg="#262626", btn_off_text="#6a6a6a", accent="#f0a830",
    accent_text="#1a1204", green="#4cd08a", red="#ff6060", dim="#6e6e6e", on_bg="#1f3d2c", on_text="#c4f2d6",
    ptt="#5a2222", ptt_edge="#8a3030", ptt_off_bg="#2a1c1c", ptt_off_edge="#3e2a2a", meter_bg="#181818",
    peak="#e2e2e2")

LIGHT = Theme(
    "Light", bg="#f1f3f7", text="#1c2433", muted="#56627a", panel="#ffffff", edge="#c2cad8", edge2="#b3bdce",
    btn="#e2e7f0", btn_hover="#d3dae8", btn_off_bg="#eceff5", btn_off_text="#a3adbf", accent="#c77700",
    accent_text="#ffffff", green="#14995c", red="#d63030", dim="#8a95aa", on_bg="#cdeedd", on_text="#0d5c38",
    ptt="#e8b4b4", ptt_edge="#c25a5a", ptt_off_bg="#f0e4e4", ptt_off_edge="#dcc4c4", meter_bg="#e9edf4",
    peak="#1c2433")

# Night red: only red tones, so it does not spoil dark-adapted eyes when operating in a dark shack or in the field.
NIGHT_RED = Theme(
    "Night red", bg="#0a0000", text="#e0786a", muted="#a65349", panel="#140404", edge="#4a1414", edge2="#5a1c1c",
    btn="#2a0b0b", btn_hover="#3d1212", btn_off_bg="#160505", btn_off_text="#6a2c28", accent="#ff4d3d",
    accent_text="#1a0000", green="#ff8a5c", red="#ff2a2a", dim="#7a2f28", on_bg="#4a1a10", on_text="#ffb199",
    ptt="#5a1010", ptt_edge="#a02020", ptt_off_bg="#1c0808", ptt_off_edge="#3a1414", meter_bg="#100202",
    peak="#e0786a")

THEMES: dict[str, Theme] = {t.name: t for t in (MIDNIGHT, DARK, LIGHT, NIGHT_RED)}
DEFAULT_THEME = MIDNIGHT.name

_STYLE = Template("""
QWidget { background:$bg; color:$text; font-size:13px; }
QGroupBox { border:1px solid $edge; border-radius:8px; margin-top:12px; padding-top:8px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:$muted; }
QPushButton { background:$btn; border:1px solid $edge2; border-radius:6px; padding:6px 10px; }
QPushButton:hover { background:$btn_hover; }
QPushButton:checked { background:$accent; color:$accent_text; border-color:$accent; font-weight:600; }
QPushButton:disabled { color:$btn_off_text; background:$btn_off_bg; }
QPushButton#ptt { background:$ptt; border-color:$ptt_edge; font-weight:700; padding:12px; }
QPushButton#ptt:pressed { background:#d42f2f; color:white; }
QPushButton#ptt:disabled { background:$ptt_off_bg; border-color:$ptt_off_edge; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
  background:$panel; border:1px solid $edge2; border-radius:6px; padding:4px 6px; }
QLabel#tx_banner { background:#d42f2f; color:white; font-weight:700; padding:4px; border-radius:6px; }
QFrame#tx_group { border:1px solid $ptt_edge; border-radius:8px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid $edge2; border-radius:4px; background:$panel; }
QCheckBox::indicator:checked { background:$accent; border-color:$accent; }
QCheckBox::indicator:disabled { border-color:$edge; background:$bg; }
QPushButton[on="true"] { background:$on_bg; border-color:$green; color:$on_text; }
QSlider::groove:horizontal { height:6px; background:$edge; border-radius:3px; }
QSlider::handle:horizontal { background:$accent; width:14px; margin:-5px 0; border-radius:7px; }
QFrame#clock_box { background:$panel; border:1px solid $edge; border-radius:8px; }
QLabel#clock { color:$accent; background:transparent; font-size:30px; font-weight:600; }
QLabel#utc_lbl { color:$muted; background:transparent; font-size:13px; font-weight:600; }
QLabel#info { color:$muted; }
QPlainTextEdit#cw_view { font-family:monospace; font-size:14px; color:$accent; }
QMenuBar::item:selected, QMenu::item:selected { background:$btn_hover; }
""")


def build_style(t: Theme) -> str:
    return _STYLE.substitute(t.__dict__)
