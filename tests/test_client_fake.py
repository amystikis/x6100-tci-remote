"""End-to-end tests of TciClient against the fake radio (real WebSocket, no hardware)."""
import asyncio

from x6100_remote.fakeradio import serve_fake
from x6100_remote.tci import TciClient


async def until(cond, timeout=3.0):
    t = 0.0
    while not cond():
        await asyncio.sleep(0.02)
        t += 0.02
        assert t < timeout, "timed out"


async def with_radio(coro, listen_only=False):
    radio, server = await serve_fake(0, listen_only)
    port = server.sockets[0].getsockname()[1]
    client = TciClient("ws://127.0.0.1:%d/" % port)
    task = asyncio.ensure_future(client.run())
    try:
        await until(lambda: client.state.ready)
        await coro(radio, client)
    finally:
        await client.close()
        task.cancel()
        server.close()
        await server.wait_closed()


def run(coro, **kw):
    asyncio.run(with_radio(coro, **kw))


def test_init_burst_populates_state():
    async def body(radio, c):
        assert c.state.device == "OpenX6X00" and c.state.freq == 7151000 and c.state.mode == "lsb"
        await until(lambda: c.state.smeter_dbm > -140)
    run(body)


def test_tune_mode_filter_agc_roundtrip():
    async def body(radio, c):
        await c.set_freq(14200000)
        await c.set_mode("usb")
        await c.set_filter(50, 2850)
        await c.set_agc("fast")
        await until(lambda: (c.state.freq, c.state.mode, c.state.filter_hi, c.state.agc)
                    == (14200000, "usb", 2850, "fast"))
    run(body)


def test_listen_only_radio_refuses_tuning_and_keying():
    async def body(radio, c):
        await c.set_freq(14200000)
        await c.set_ptt(True)
        await asyncio.sleep(0.3)
        assert c.state.freq == 7151000 and c.state.trx is False
    run(body, listen_only=True)


def test_rx_audio_stream():
    async def body(radio, c):
        got = []
        c.on_audio = lambda h, s: got.append((h.sample_rate, s.size))
        await c.start_audio()
        await until(lambda: len(got) >= 3)
        assert got[0] == (48000, 2048)
        await c.stop_audio()
    run(body)


def test_ptt_with_radio_microphone():
    async def body(radio, c):
        await c.set_ptt(True)
        await until(lambda: c.state.trx)
        await c.set_ptt(False)
        await until(lambda: not c.state.trx)
        assert radio.tx_audio_frames == 0
    run(body)


def test_ptt_with_tci_audio_answers_tx_chrono():
    import numpy as np

    async def body(radio, c):
        c.tx_source = lambda n: np.zeros((n, 2), dtype=np.float32)
        await c.set_ptt(True, use_tci_audio=True)
        await until(lambda: radio.tx_audio_frames >= 2)
        await c.set_ptt(False)
        await until(lambda: not c.state.trx)
    run(body)
