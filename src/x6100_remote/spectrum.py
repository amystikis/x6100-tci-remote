"""Spectrum feed of the OpenX6X00 panel server (WebSocket port 50002, the same server as the screen mirror).

Observed on a real radio (firmware v0.3.9):

* The server sends text lines on connect (``hello ...``, ``size 800 480``, ``role view 0 -``, ...) and then
  ``m <dBm>`` S-meter lines. Descriptive lines (bands, plan, spots, state, cw, ft8) are decoded by
  :mod:`x6100_remote.panelinfo`; the rest is ignored.
* ``screen 0`` stops the ~55 kB JPEG screen frames, ``panel 1`` starts the spectrum frames.
* A spectrum frame is a binary message of 16 + 1024 bytes (little endian)::

      u16 magic = 0xFFFF | u16 nbins = 1024 | u32 centre Hz | u32 span Hz | u32 frame counter | nbins x u8

  The centre is the VFO frequency and the span was 100 kHz. Bin values are unsigned bytes of an
  *uncalibrated* level scale (the radio's own web page auto-scales them), so the GUI does the same.

The same socket also accepts radio key presses and device pairing (``pair <6-digit code> <name>`` answers
``paired <role> ...``; a paired device authenticates with ``auth <key>`` and then has the role ``operate`` or
``admin``). This client sends only what :func:`is_allowed` accepts: the three subscription commands, pairing and
auth, ``control take|release``, and presses of the few keys in :data:`KEY_NAMES`. It never sends POWER, PTT or any
other key, and it presses keys only when the radio reports an operate/admin role.
"""
from __future__ import annotations

import asyncio
import logging
import re
import struct
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import websockets

from .panelinfo import PanelInfo

log = logging.getLogger(__name__)

PANEL_PORT = 50002
MAGIC = 0xFFFF
_HEADER = struct.Struct("<HHIII")
HEADER_SIZE = _HEADER.size            # 16
ALLOWED_COMMANDS = ("screen 0", "panel 1", "ping 1", "control take", "control release")
KEY_NAMES = ("PRE", "AB", "VM", "FST", "ATU")          # the only radio keys this app will ever press
_ALLOWED_RE = (re.compile(r"key (%s) [01]" % "|".join(KEY_NAMES)),
               re.compile(r"auth [0-9a-fA-F]{16,128}"),
               re.compile(r"pair \d{6} [A-Za-z0-9 ._-]{1,32}"))
_TOKEN_RE = re.compile(r"[0-9a-fA-F]{16,128}")


def is_allowed(text: str) -> bool:
    return text in ALLOWED_COMMANDS or any(r.fullmatch(text) for r in _ALLOWED_RE)


class ControlDenied(RuntimeError):
    """The radio does not let this app operate it (not paired, or not allowed)."""


@dataclass
class SpectrumFrame:
    center_hz: int
    span_hz: int
    seq: int
    bins: np.ndarray                  # uint8, length nbins, low frequency first

    @property
    def hz_per_bin(self) -> float:
        return self.span_hz / max(1, len(self.bins))

    def freq_at(self, index: float) -> float:
        """Frequency of a (fractional) bin index."""
        return self.center_hz - self.span_hz / 2 + index * self.hz_per_bin


def parse_frame(data: bytes) -> Optional[SpectrumFrame]:
    """Return the frame, or ``None`` if ``data`` is not a spectrum frame (e.g. a JPEG screen frame)."""
    if len(data) < HEADER_SIZE:
        return None
    magic, nbins, center, span, seq = _HEADER.unpack_from(data, 0)
    if magic != MAGIC or nbins == 0 or len(data) != HEADER_SIZE + nbins or span == 0:
        return None
    bins = np.frombuffer(data, dtype=np.uint8, count=nbins, offset=HEADER_SIZE)
    return SpectrumFrame(center, span, seq, bins)


def pack_frame(center_hz: int, span_hz: int, seq: int, bins: np.ndarray) -> bytes:
    """Build a frame (used by the fake radio and tests)."""
    b = np.asarray(bins, dtype=np.uint8)
    return _HEADER.pack(MAGIC, len(b), center_hz, span_hz, seq) + b.tobytes()


class PanelClient:
    """Connect once with :meth:`run`; it returns when the socket closes.

    Callbacks run on the event loop thread: ``on_open()`` after subscribing, ``on_frame(frame)`` for
    every spectrum frame.
    """

    def __init__(self, url: str, keepalive: float = 15.0, info: Optional[PanelInfo] = None,
                 token: Optional[str] = None) -> None:
        self.url = url
        self.keepalive = keepalive
        self.token = token if token and _TOKEN_RE.fullmatch(token) else None
        self.on_paired: Optional[Callable[[str, Optional[str]], None]] = None   # (role, key or None)
        self.info = info if info is not None else PanelInfo()
        self.on_info: Optional[Callable[[str], None]] = None      # called with "spots", "bands", "cw", ...
        self.on_open: Optional[Callable[[], None]] = None
        self.on_frame: Optional[Callable[[SpectrumFrame], None]] = None
        self.frames = 0
        self._ws = None

    async def _send(self, text: str) -> None:
        if not is_allowed(text):
            raise ValueError("refusing to send %r to the panel server" % text)
        if self._ws is not None:
            await self._ws.send(text)

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(self.keepalive)
            await self._send("ping 1")

    async def run(self) -> None:
        async with websockets.connect(self.url, max_size=None, open_timeout=6,
                                      ping_interval=20, ping_timeout=20) as ws:
            self._ws = ws
            if self.token:
                await self._send("auth " + self.token)
            await self._send("screen 0")          # we do not want the JPEG screen mirror
            await self._send("panel 1")           # start the spectrum frames
            if self.on_open:
                self.on_open()
            ka = asyncio.ensure_future(self._keepalive())
            try:
                async for msg in ws:
                    if isinstance(msg, str):
                        if msg.startswith("paired "):
                            words = msg.split()
                            key = next((w for w in words[2:] if _TOKEN_RE.fullmatch(w)), None)
                            self.info.role = words[1] if len(words) > 1 else self.info.role
                            if self.on_paired:
                                self.on_paired(self.info.role, key)
                            continue
                        kind = self.info.apply(msg)
                        if kind and self.on_info:
                            self.on_info(kind)
                        continue
                    frame = parse_frame(msg)
                    if frame is not None:
                        self.frames += 1
                        if self.on_frame:
                            self.on_frame(frame)
            finally:
                ka.cancel()
                self._ws = None

    async def pair(self, code: str, name: str) -> None:
        """Ask the radio to pair this app. The reply arrives via ``on_paired``."""
        await self._send("pair %s %s" % (code, name))

    async def press(self, key: str, hold: float = 0.12) -> None:
        """Press and release one of :data:`KEY_NAMES` on the radio. Needs an operate/admin role."""
        if key not in KEY_NAMES:
            raise ValueError("key %r is not allowed" % key)
        if self.info.role not in ("operate", "admin"):
            raise ControlDenied("This app is not paired with the radio, so it may only watch. Use Pair...")
        await self._send("control take")
        await asyncio.sleep(0.2)
        try:
            await self._send("key %s 1" % key)
            await asyncio.sleep(hold)
        finally:
            await self._send("key %s 0" % key)
            await asyncio.sleep(0.1)
            await self._send("control release")

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
