"""A small fake TCI radio for development and tests (no hardware, no RF).

    python -m x6100_remote.fakeradio --port 50001 [--listen-only]

It mimics the initial burst and behaviour seen on a real OpenX6X00 radio: state echoes,
a live S-meter, 48 kHz float32 stereo RX audio after ``audio_start``, and TX-chrono
requests when keyed with TCI audio."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random

import numpy as np
from websockets.asyncio.server import serve

from .spectrum import pack_frame
from .tci.protocol import format_command, parse_commands
from .tci.stream import (FORMAT_FLOAT32, STREAM_RX_AUDIO, STREAM_TX_AUDIO, STREAM_TX_CHRONO,
                         StreamHeader, decode_stream)


class FakeRadio:
    def __init__(self, listen_only: bool = False) -> None:
        self.listen_only = listen_only
        self.vfo = {0: 7151000, 1: 7100000}
        self.mode = "lsb"
        self.filter = (-3050, -50)
        self.agc = "off"
        self.rit_enable, self.rit_offset, self.split, self.lock = False, 0, False, False
        self.drive = 24
        self.trx = False
        self.clients: set = set()
        self.tx_audio_frames = 0
        self.keyed_with_tci = False
        self.log: list[str] = []          # every text command received (for tests)

    # state -> messages ------------------------------------------------------
    def init_burst(self) -> list[str]:
        f = format_command
        return [
            "protocol:ExpertSDR3,1.9;", "device:OpenX6X00;", "receive_only:false;", "trx_count:1;",
            "channels_count:1;", "vfo_limits:100000,55000000;", "if_limits:-48000,48000;",
            "modulations_list:lsb,usb,digl,digu,cw,cwr,am,nfm;", "audio_samplerate:48000;",
            "audio_stream_sample_type:float32;", "audio_stream_channels:2;", "audio_stream_samples:2048;",
            f("vfo", 0, 0, self.vfo[0]), f("vfo", 0, 1, self.vfo[1]), f("modulation", 0, self.mode),
            f("rx_filter_band", 0, *self.filter), f("agc_mode", 0, self.agc),
            f("rit_enable", 0, self.rit_enable), f("rit_offset", 0, self.rit_offset),
            "rx_enable:0,true;", "tx_enable:0,true;", f("lock", 0, self.lock),
            f("split_enable", 0, self.split), f("drive", 0, self.drive), f("trx", 0, self.trx),
            "start;", "ready;",
        ]

    async def broadcast(self, text: str) -> None:
        for ws in list(self.clients):
            try:
                await ws.send(text)
            except Exception:
                self.clients.discard(ws)

    # command handling ---------------------------------------------------------
    async def handle_command(self, ws, cmd, session: dict) -> None:
        n, f = cmd.name, format_command
        self.log.append(str(cmd))
        operating = {"vfo", "modulation", "trx", "drive"}
        if self.listen_only and n in operating:
            # a listen-only radio answers with the unchanged state
            if n == "vfo":
                await ws.send(f("vfo", 0, cmd.int(1), self.vfo.get(cmd.int(1), 0)))
            elif n == "modulation":
                await ws.send(f("modulation", 0, self.mode))
            elif n == "trx":
                await ws.send(f("trx", 0, False))
            else:
                await ws.send(f("drive", 0, self.drive))
            return
        if n == "vfo":
            self.vfo[cmd.int(1)] = cmd.int(2)
            await self.broadcast(f("vfo", 0, cmd.int(1), self.vfo[cmd.int(1)]))
        elif n == "modulation":
            self.mode = cmd.str(1)
            await self.broadcast(f("modulation", 0, self.mode))
        elif n == "rx_filter_band":
            self.filter = (cmd.int(1), cmd.int(2))
            await self.broadcast(f("rx_filter_band", 0, *self.filter))
        elif n == "agc_mode":
            self.agc = cmd.str(1)
            await self.broadcast(f("agc_mode", 0, self.agc))
        elif n == "rit_enable":
            self.rit_enable = cmd.bool(1)
            await self.broadcast(f("rit_enable", 0, self.rit_enable))
        elif n == "rit_offset":
            self.rit_offset = cmd.int(1)
            await self.broadcast(f("rit_offset", 0, self.rit_offset))
        elif n == "split_enable":
            self.split = cmd.bool(1)
            await self.broadcast(f("split_enable", 0, self.split))
        elif n == "lock":
            self.lock = cmd.bool(1)
            await self.broadcast(f("lock", 0, self.lock))
        elif n == "drive":
            self.drive = cmd.int(1) if len(cmd.args) > 1 else cmd.int(0)
            await self.broadcast(f("drive", 0, self.drive))
        elif n == "trx":
            self.trx = cmd.bool(1)
            self.keyed_with_tci = self.trx and cmd.str(2) == "tci"
            await self.broadcast(f("trx", 0, self.trx))
        elif n == "audio_start":
            session["audio"] = True
        elif n == "audio_stop":
            session["audio"] = False

    async def audio_loop(self, ws, session: dict) -> None:
        phase = 0.0
        step = 2 * math.pi * 440.0 / 48000.0
        while True:
            await asyncio.sleep(2048 / 2 / 48000)           # 1024 stereo frames per packet
            if session.get("audio"):
                t = phase + step * np.arange(1024)
                mono = (0.2 * np.sin(t)).astype("<f4")
                phase = (phase + step * 1024) % (2 * math.pi)
                hdr = StreamHeader(0, 48000, FORMAT_FLOAT32, 0, 0, 2048, STREAM_RX_AUDIO)
                await ws.send(hdr.pack() + np.repeat(mono, 2).tobytes())
            if self.trx and self.keyed_with_tci:
                hdr = StreamHeader(0, 48000, FORMAT_FLOAT32, 0, 0, 2048, STREAM_TX_CHRONO)
                await ws.send(hdr.pack() + bytes(2048 * 4))

    async def smeter_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(0.1)
            await ws.send(format_command("rx_smeter", 0, 0, -90 + random.randint(-4, 4)))

    async def handler(self, ws) -> None:
        session: dict = {}
        self.clients.add(ws)
        for m in self.init_burst():
            await ws.send(m)
        tasks = [asyncio.ensure_future(self.audio_loop(ws, session)),
                 asyncio.ensure_future(self.smeter_loop(ws))]
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    for cmd in parse_commands(msg):
                        await self.handle_command(ws, cmd, session)
                else:
                    hdr, _ = decode_stream(msg)
                    if hdr.type == STREAM_TX_AUDIO:
                        self.tx_audio_frames += 1
        except Exception:
            pass
        finally:
            for t in tasks:
                t.cancel()
            self.clients.discard(ws)


async def serve_fake(port: int = 50001, listen_only: bool = False, host: str = "127.0.0.1"):
    radio = FakeRadio(listen_only)
    server = await serve(radio.handler, host, port, max_size=None)
    return radio, server


class FakePanel:
    """Fake of the radio's panel server (port 50002): hello lines, ``m`` S-meter lines and, after
    ``panel 1``, spectrum frames centred on the fake radio's VFO. ``screen 1`` sends junk 'JPEG' frames."""

    SPAN = 100_000
    NBINS = 1024
    FPS = 14
    SPOT_PERIOD = 15.0                # seconds between spot lists, as on the real radio
    BANDS = [{"n": "80m", "a": 3500000, "b": 3800000}, {"n": "40m", "a": 7000000, "b": 7300000},
             {"n": "20m", "a": 14000000, "b": 14350000}]
    PLAN = [[7000000, 7040000, 0], [7040000, 7060000, 1], [7060000, 7200000, 2], [7200000, 7300000, 3]]
    SPOTS = [{"f": 7_146_000, "c": "DL1ABC", "m": "SSB", "a": 2, "s": "G4XYZ-#", "k": "CQ DX", "al": 0},
             {"f": 7_150_400, "c": "AC4WW", "m": "CW", "a": 0, "s": "WB6BEE-#", "k": "POTA US-9774 CW", "al": 0},
             {"f": 7_150_900, "c": "SP9XYZ", "m": "SSB", "a": 25, "s": "DK0ABC", "k": "", "al": 0},
             {"f": 7_158_000, "c": "K1TTT", "m": "SSB", "a": 5, "s": "N2AB", "k": "SOTA W1/HA-001", "al": 1},
             {"f": 7_043_000, "c": "EA8ZZ", "m": "FT8", "a": 1, "s": "EA4A", "k": "", "al": 0}]

    PAIR_CODE = "123456"
    TOKEN = "0123456789abcdef0123456789abcdef"

    def __init__(self, radio: FakeRadio) -> None:
        self.radio = radio
        self.log: list[str] = []          # every text command received (for tests)
        self.code_shown = False            # set by "pair?", like the code appearing on the real radio's screen
        self.keys_pressed: list[str] = []  # keys honoured while paired and holding control
        self.seq = 0
        self.pre, self.atu, self.vfo_b = 1, 1, 0

    def spectrum_bins(self, center: int) -> np.ndarray:
        rng = np.random.default_rng()
        bins = 142 + rng.normal(0, 3, self.NBINS)
        hz_per_bin = self.SPAN / self.NBINS
        # a few carriers at fixed absolute frequencies, so they move when the fake VFO is retuned
        for f, level, width in ((7_146_500, 30, 14), (7_153_200, 22, 10), (7_160_000, 38, 3), (7_141_000, 16, 25)):
            idx = (f - (center - self.SPAN / 2)) / hz_per_bin
            if -50 < idx < self.NBINS + 50:
                x = np.arange(self.NBINS)
                bins += level * np.exp(-((x - idx) / (width / 2.0)) ** 2) * (0.7 + 0.3 * rng.random())
        return np.clip(bins, 0, 255).astype(np.uint8)

    async def spectrum_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(1 / self.FPS)
            self.seq += 1
            await ws.send(pack_frame(self.radio.vfo[0], self.SPAN, self.seq, self.spectrum_bins(self.radio.vfo[0])))

    def state_line(self) -> str:
        return "state " + json.dumps({"freq": self.radio.vfo[0], "mode": 0, "flo": 50, "fhi": 3050, "pre": self.pre,
                                      "att": 0, "nb": 0, "nr": 1, "sql": 0, "rfg": 70, "vol": 20, "pwr": 5.0,
                                      "step": 500, "zoom": 4, "vfo": self.vfo_b, "atu": self.atu, "bat": 76,
                                      "tx": 0, "lock": 0}, separators=(",", ":"))

    def info_lines(self) -> list[str]:
        return ["bands " + json.dumps(self.BANDS, separators=(",", ":")),
                "plan " + json.dumps(self.PLAN, separators=(",", ":")),
                self.state_line(),
                "ft8 " + json.dumps({"open": 1, "tx": 0, "next": "", "logged": ""}, separators=(",", ":")),
                "cw " + json.dumps("CQ CQ DE "),
                "spots " + json.dumps(self.SPOTS, separators=(",", ":"))]

    async def info_loop(self, ws) -> None:
        n = 0
        while True:
            await asyncio.sleep(self.SPOT_PERIOD)
            n += 1
            await ws.send("spots " + json.dumps(self.SPOTS, separators=(",", ":")))
            await ws.send("cw " + json.dumps("K1TTT %d " % n))

    async def handle_control(self, ws, msg: str, sess: dict) -> None:
        """Auth, pairing, control and key presses, like the real radio's panel server (format inferred)."""
        parts = msg.split()
        if msg.startswith("auth ") and parts[1] == self.TOKEN:
            sess["role"] = "operate"
            await ws.send("role operate 1 tester")
        elif msg == "pair?":
            self.code_shown = True
        elif msg.startswith("pair ") and len(parts) >= 3 and parts[1] == self.PAIR_CODE and self.code_shown:
            sess["role"] = "operate"
            await ws.send("paired operate " + self.TOKEN)
            await ws.send("role operate 1 " + " ".join(parts[2:]))
        elif msg == "control take" and sess["role"] == "operate":
            sess["control"] = True
            await ws.send("ctl me 1")
        elif msg == "control release":
            sess["control"] = False
            await ws.send("ctl none 0")
        elif msg.startswith("key ") and len(parts) == 3 and parts[2] == "1":
            if sess["role"] == "operate" and sess["control"]:
                self.keys_pressed.append(parts[1])
                if parts[1] == "PRE":
                    self.pre = (self.pre + 1) % 3
                elif parts[1] == "ATU":
                    self.atu ^= 1
                elif parts[1] == "AB":
                    self.vfo_b ^= 1
                await ws.send(self.state_line())

    async def screen_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(0.11)
            await ws.send(bytes([32, 3, 224, 1, 0, 0, 0, 0, 255, 216]) + bytes(50_000))

    async def handler(self, ws) -> None:
        loops: dict[str, asyncio.Future] = {}
        sess = {"role": "view", "control": False}

        def toggle(name: str, on: bool, make) -> None:
            if on and name not in loops:
                loops[name] = asyncio.ensure_future(make(ws))
            elif not on and name in loops:
                loops.pop(name).cancel()

        try:
            for line in ("hello OpenX6X00 - fake", "size 800 480", "role view 0 -", "ctl none 0", *self.info_lines()):
                await ws.send(line)
            loops["info"] = asyncio.ensure_future(self.info_loop(ws))
            async for msg in ws:
                if not isinstance(msg, str):
                    continue
                self.log.append(msg)
                await self.handle_control(ws, msg, sess)
                if msg.startswith("panel "):
                    toggle("panel", msg.split()[1] == "1", self.spectrum_loop)
                elif msg.startswith("screen "):
                    toggle("screen", msg.split()[1] == "1", self.screen_loop)
        except Exception:
            pass
        finally:
            for t in loops.values():
                t.cancel()


async def serve_fake_panel(radio: FakeRadio, port: int = 50002, host: str = "127.0.0.1"):
    panel = FakePanel(radio)
    server = await serve(panel.handler, host, port, max_size=None)
    return panel, server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=50001)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--panel-port", type=int, default=50002, help="spectrum server port (-1 to disable)")
    ap.add_argument("--listen-only", action="store_true")
    a = ap.parse_args()

    async def run():
        radio, server = await serve_fake(a.port, a.listen_only, a.host)
        print("fake TCI radio on ws://%s:%d/ (%s)" % (a.host, a.port, "listen-only" if a.listen_only else "operate"))
        if a.panel_port >= 0:
            await serve_fake_panel(radio, a.panel_port, a.host)
            print("fake panel (spectrum) on ws://%s:%d/" % (a.host, a.panel_port))
        await server.serve_forever()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
