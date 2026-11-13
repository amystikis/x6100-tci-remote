import numpy as np
import pytest

from x6100_remote.tci import (Command, RadioState, StreamHeader, dbm_to_s, decode_stream,
                              encode_tx_audio, format_command, parse_commands)
from x6100_remote.tci.stream import decode_samples


def test_parse_multiple_commands_in_one_frame():
    cmds = parse_commands("vfo:0,0,7151000;modulation:0,lsb;start;ready;")
    assert [c.name for c in cmds] == ["vfo", "modulation", "start", "ready"]
    assert cmds[0].args == ("0", "0", "7151000") and cmds[2].args == ()


def test_format_command_booleans_and_numbers():
    assert format_command("trx", 0, True, "tci") == "trx:0,true,tci;"
    assert format_command("vfo", 0, 0, 7151000) == "vfo:0,0,7151000;"
    assert format_command("audio_start", 0) == "audio_start:0;"
    assert format_command("ready") == "ready;"


def test_state_applies_real_radio_init_burst():
    st = RadioState()
    burst = ("protocol:ExpertSDR3,1.9;device:OpenX6X00;vfo_limits:100000,55000000;if_limits:-48000,48000;"
             "modulations_list:lsb,usb,digl,digu,cw,cwr,am,nfm;vfo:0,0,7151000;modulation:0,lsb;"
             "rx_filter_band:0,-3050,-50;agc_mode:0,off;drive:0,24;trx:0,false;start;ready;rx_smeter:0,0,-92;")
    for c in parse_commands(burst):
        st.apply(c)
    assert (st.device, st.freq, st.mode, st.filter_lo, st.filter_hi) == ("OpenX6X00", 7151000, "lsb", -3050, -50)
    assert st.if_limits == (-48000, 48000) and "nfm" in st.modulations
    assert st.drive == 24 and st.trx is False and st.ready and st.smeter_dbm == -92.0


def test_state_ignores_other_receivers_and_unknown():
    st = RadioState()
    assert st.apply(Command("vfo", ("1", "0", "14200000"))) is None
    assert st.freq == 0
    assert st.apply(Command("something_new", ("1",))) is None


@pytest.mark.parametrize("dbm,label", [(-110, "S3"), (-73, "S9"), (-60, "S9+10"), (-13, "S9+60")])
def test_dbm_to_s(dbm, label):
    assert dbm_to_s(dbm)[0] == label


def test_stream_header_roundtrip_is_64_bytes_little_endian():
    h = StreamHeader(0, 48000, 3, 0, 0, 2048, 1)
    raw = h.pack()
    assert len(raw) == 64 and raw[:4] == b"\x00\x00\x00\x00" and raw[4:8] == (48000).to_bytes(4, "little")
    assert StreamHeader.unpack(raw) == h


def test_tx_audio_encode_decode():
    x = np.linspace(-1, 1, 16, dtype=np.float32).reshape(8, 2)
    hdr, s = decode_stream(encode_tx_audio(x))
    assert hdr.type == 2 and hdr.length == 16 and np.allclose(s, x.reshape(-1))


def test_sample_formats():
    i16 = np.array([0, 16384, -32768], dtype="<i2").tobytes()
    assert np.allclose(decode_samples(0, i16, 3), [0, 0.5, -1.0])
    i24 = b"".join(int(v).to_bytes(3, "little", signed=True) for v in (0, 4194304, -8388608))
    assert np.allclose(decode_samples(1, i24, 3), [0, 0.5, -1.0])
    with pytest.raises(ValueError):
        decode_samples(9, b"", 0)
