"""Runs the asyncio TCI client on its own thread and bridges it to Qt signals."""
from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from ..panelinfo import PanelInfo
from ..spectrum import PanelClient
from ..tci import Command, RadioState, TciClient


class TciWorker(QObject):
    status = Signal(str, str)       # ("connecting" | "connected" | "disconnected", detail)
    changed = Signal(str)           # name of the RadioState field that changed
    audio = Signal(bytes, int)      # float32 interleaved stereo, sample rate
    raw = Signal(str)               # every text command, for the protocol log
    spectrum = Signal(object)       # SpectrumFrame from the panel server
    panel_info = Signal(str)        # "spots" | "bands" | "plan" | "state" | "cw" | "ft8" (data is in worker.info)
    panel_status = Signal(str, str)  # same states as `status`, for the spectrum feed

    def __init__(self) -> None:
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="tci-loop")
        self._thread.start()
        self.client: Optional[TciClient] = None
        self.state = RadioState()
        self._task: Optional[asyncio.Task] = None
        self._want = False
        self._announced = False
        self._tx_source: Optional[Callable] = None
        self._audio_on = False
        self.info = PanelInfo()
        self._panel_task: Optional[asyncio.Task] = None
        self._panel_want = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    # connection -------------------------------------------------------------
    def connect_to(self, url: str) -> None:
        self.submit(self._connect(url))

    def disconnect_from(self) -> None:
        self.submit(self._disconnect())
        self.disconnect_panel()

    async def _connect(self, url: str) -> None:
        await self._disconnect()
        self._want = True
        self._task = self.loop.create_task(self._session(url))

    async def _disconnect(self) -> None:
        self._want = False
        if self.client is not None:
            try:
                await self.client.send("trx", 0, False)       # never leave the radio keyed
            except Exception:
                pass
            await self.client.close()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.status.emit("disconnected", "")

    async def _session(self, url: str) -> None:
        backoff = 1
        while self._want:
            self.status.emit("connecting", url)
            self._announced = False
            c = TciClient(url)
            c.tx_source = self._tx_source
            c.on_command = self._on_command
            c.on_audio = lambda h, s: self.audio.emit(s.tobytes(), h.sample_rate)
            self.client, self.state = c, c.state
            reason = "connection closed"
            try:
                await c.run()
            except asyncio.CancelledError:
                raise
            except Exception as e:                        # refused, timeout, DNS, ...
                reason = str(e) or e.__class__.__name__
            finally:
                self.client = None
            if not self._want:
                break
            self.status.emit("disconnected", "%s - retrying in %ds" % (reason, backoff))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

    def _on_command(self, cmd: Command, changed: Optional[str]) -> None:
        if not self._announced:
            self._announced = True
            self.status.emit("connected", "")
            if self._audio_on:
                self.submit(self._send("audio_start", (0,)))
        if cmd.name != "rx_smeter":
            self.raw.emit(str(cmd))
        if changed:
            self.changed.emit(changed)

    # spectrum feed (panel server) -----------------------------------------------------------
    def connect_panel(self, url: str) -> None:
        self.submit(self._connect_panel(url))

    def disconnect_panel(self) -> None:
        self.submit(self._disconnect_panel())

    async def _connect_panel(self, url: str) -> None:
        await self._disconnect_panel()
        self.info = PanelInfo()                           # never show another radio's spots or bands
        self._panel_want = True
        self._panel_task = self.loop.create_task(self._panel_session(url))

    async def _disconnect_panel(self) -> None:
        self._panel_want = False
        if self._panel_task is not None:
            self._panel_task.cancel()
            self._panel_task = None
        self.panel_status.emit("disconnected", "")

    async def _panel_session(self, url: str) -> None:
        backoff = 1
        while self._panel_want:
            self.panel_status.emit("connecting", url)
            c = PanelClient(url, info=self.info)
            c.on_info = self.panel_info.emit
            c.on_open = lambda: self.panel_status.emit("connected", "")
            c.on_frame = self.spectrum.emit
            reason = "connection closed"
            try:
                await c.run()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                reason = str(e) or e.__class__.__name__
            if not self._panel_want:
                break
            self.panel_status.emit("disconnected", "%s - retrying in %ds" % (reason, backoff))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

    # commands ----------------------------------------------------------------------
    def send(self, name: str, *args: object) -> None:
        self.submit(self._send(name, args))

    async def _send(self, name: str, args: tuple) -> None:
        if self.client is not None:
            await self.client.send(name, *args)

    def set_ptt(self, on: bool, use_tci_audio: bool = False) -> None:
        async def go():
            if self.client is not None:
                await self.client.set_ptt(on, use_tci_audio)
        self.submit(go())

    def set_audio(self, on: bool) -> None:
        self._audio_on = on
        self.send("audio_start" if on else "audio_stop", 0)

    def set_tx_source(self, fn: Optional[Callable]) -> None:
        self._tx_source = fn
        if self.client is not None:
            self.client.tx_source = fn

    def shutdown(self) -> None:
        async def stop_all():
            await self._disconnect_panel()
            await self._disconnect()

        fut = asyncio.run_coroutine_threadsafe(stop_all(), self.loop)
        try:
            fut.result(timeout=2)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
