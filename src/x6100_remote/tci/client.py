"""Asyncio TCI client. One WebSocket carries text commands and binary audio/IQ frames."""
from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np
import websockets

from .protocol import Command, format_command, parse_commands
from .state import RadioState
from .stream import STREAM_RX_AUDIO, STREAM_TX_CHRONO, decode_stream, encode_tx_audio, StreamHeader, HEADER_SIZE

log = logging.getLogger(__name__)

CommandCb = Callable[[Command, Optional[str]], None]
AudioCb = Callable[[StreamHeader, np.ndarray], None]
TxSource = Callable[[int], np.ndarray]        # frames wanted -> float32 array (n, 2)


class TciClient:
    """Connect once with :meth:`run`; it returns when the socket closes.

    Callbacks run on the event loop thread:
      on_command(cmd, changed_field)   every parsed text command (state already updated)
      on_audio(header, samples)        RX audio frames (float32, interleaved stereo)
      on_stream(header, frame)         IQ/other binary frames, raw
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.state = RadioState()
        self.on_command: Optional[CommandCb] = None
        self.on_audio: Optional[AudioCb] = None
        self.on_stream: Optional[Callable[[StreamHeader, bytes], None]] = None
        self.tx_source: Optional[TxSource] = None
        self.connected = False
        self._ws = None
        self.rx_frames = 0
        self.tx_frames = 0

    # connection --------------------------------------------------------------
    async def run(self) -> None:
        async with websockets.connect(self.url, max_size=None, open_timeout=6,
                                      ping_interval=20, ping_timeout=20) as ws:
            self._ws = ws
            self.connected = True
            try:
                async for msg in ws:
                    if isinstance(msg, str):
                        self._on_text(msg)
                    else:
                        await self._on_binary(msg)
            finally:
                self.connected = False
                self._ws = None

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()

    # sending -------------------------------------------------------------------
    async def send(self, name: str, *args: object) -> None:
        if self._ws is None:
            return
        await self._ws.send(format_command(name, *args))

    async def send_raw(self, text: str) -> None:
        if self._ws is not None:
            await self._ws.send(text)

    # convenience commands (rx 0) -------------------------------------------------
    async def set_freq(self, hz: int, channel: int = 0) -> None:
        await self.send("vfo", 0, channel, int(hz))

    async def set_mode(self, mode: str) -> None:
        await self.send("modulation", 0, mode)

    async def set_filter(self, lo: int, hi: int) -> None:
        await self.send("rx_filter_band", 0, int(lo), int(hi))

    async def set_agc(self, mode: str) -> None:
        await self.send("agc_mode", 0, mode)

    async def set_rit(self, enable: bool | None = None, offset: int | None = None) -> None:
        if enable is not None:
            await self.send("rit_enable", 0, enable)
        if offset is not None:
            await self.send("rit_offset", 0, int(offset))

    async def set_split(self, enable: bool) -> None:
        await self.send("split_enable", 0, enable)

    async def set_lock(self, enable: bool) -> None:
        await self.send("lock", 0, enable)

    async def set_drive(self, value: int) -> None:
        await self.send("drive", 0, int(value))

    async def set_ptt(self, on: bool, use_tci_audio: bool = False) -> None:
        """Key the transmitter. ``use_tci_audio`` takes TX audio from this client instead
        of the radio's own microphone."""
        if on and use_tci_audio:
            await self.send("trx", 0, True, "tci")
        else:
            await self.send("trx", 0, on)

    async def start_audio(self) -> None:
        await self.send("audio_start", 0)

    async def stop_audio(self) -> None:
        await self.send("audio_stop", 0)

    # receiving -------------------------------------------------------------------
    def _on_text(self, text: str) -> None:
        for cmd in parse_commands(text):
            changed = self.state.apply(cmd)
            if self.on_command:
                self.on_command(cmd, changed)

    async def _on_binary(self, frame: bytes) -> None:
        if len(frame) < HEADER_SIZE:
            return
        hdr = StreamHeader.unpack(frame)
        if hdr.type == STREAM_RX_AUDIO:
            self.rx_frames += 1
            if self.on_audio:
                _, samples = decode_stream(frame)
                self.on_audio(hdr, samples)
        elif hdr.type == STREAM_TX_CHRONO:
            # the radio asks for `length` TX samples; answer with the same count
            if self.tx_source is not None and self._ws is not None:
                frames = max(1, hdr.length // 2)
                data = self.tx_source(frames)
                self.tx_frames += 1
                await self._ws.send(encode_tx_audio(data, hdr.sample_rate or 48000, hdr.receiver))
        elif self.on_stream:
            self.on_stream(hdr, frame)
