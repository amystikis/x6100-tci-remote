#!/usr/bin/env python3
"""Probe a radio's TCI server from the command line.

Default mode is passive: connect, print what the radio announces, show a few seconds of
traffic and summarise binary frames. It sends nothing.

    python scripts/probe_tci.py 192.168.0.150

``--iq-test`` ASKS the radio to start an IQ stream (iq_samplerate / iq_start) and reports
whether binary IQ frames arrive. This sends commands and may change a stream setting shared
with other TCI clients, so it needs the explicit ``--yes-send-commands`` flag. It never keys
the transmitter. It tells you whether an independent SDR (own waterfall/demodulator) is
possible with your firmware.
"""
import argparse
import asyncio
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from x6100_remote.tci import TciClient  # noqa: E402
from x6100_remote.tci.stream import HEADER_SIZE  # noqa: E402

TYPE_NAMES = {0: "IQ", 1: "RX audio", 2: "TX audio", 3: "TX chrono"}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=50001)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--iq-test", action="store_true")
    ap.add_argument("--iq-rate", type=int, default=96000)
    ap.add_argument("--yes-send-commands", action="store_true")
    a = ap.parse_args()
    if a.iq_test and not a.yes_send_commands:
        print("--iq-test sends commands to the radio; add --yes-send-commands to confirm.")
        return 2

    seen: list[str] = []
    bins: collections.Counter = collections.Counter()
    sizes: dict = {}
    c = TciClient("ws://%s:%d/" % (a.host, a.port))
    c.on_command = lambda cmd, ch: seen.append(str(cmd)) if cmd.name != "rx_smeter" else None

    def on_stream(h, frame):
        bins[TYPE_NAMES.get(h.type, "type %d" % h.type)] += 1
        sizes.setdefault(h.type, (h.sample_rate, h.format, h.length, len(frame) - HEADER_SIZE))
    c.on_stream = on_stream
    c.on_audio = lambda h, s: on_stream(h, b"\0" * HEADER_SIZE)

    task = asyncio.ensure_future(c.run())
    await asyncio.sleep(1.5)
    if not c.connected:
        why = task.exception() if task.done() and not task.cancelled() else "no answer"
        print("could not connect to ws://%s:%d/ (%s)" % (a.host, a.port, why))
        print("Check the address, and that the TCI server is enabled on the radio's /tci page.")
        task.cancel()
        return 1
    if a.iq_test:
        print("sending: iq_samplerate:%d; iq_start:0;" % a.iq_rate)
        await c.send_raw("iq_samplerate:%d;" % a.iq_rate)
        await c.send_raw("iq_start:0;")
    await asyncio.sleep(a.seconds)
    if a.iq_test:
        await c.send_raw("iq_stop:0;")
    await c.close()
    task.cancel()

    print("\n-- announced by the radio (%d messages, S-meter hidden) --" % len(seen))
    print("\n".join(seen[:40]))
    print("\n-- binary frames --")
    if not bins:
        print("none received")
    for k, n in bins.items():
        print("%-10s %d frames" % (k, n))
    for t, (rate, fmt, length, payload) in sizes.items():
        print("  %s: sample_rate=%s format=%s length=%s payload_bytes=%s"
              % (TYPE_NAMES.get(t, t), rate, fmt, length, payload))
    if a.iq_test:
        ok = bins.get("IQ", 0) > 0
        print("\nRESULT: radio %s IQ over TCI at %d Hz" % ("STREAMS" if ok else "did NOT stream", a.iq_rate))
        return 0 if ok else 3
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
