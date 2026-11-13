"""Radio state model, updated from incoming TCI commands."""
from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import Command


@dataclass
class RadioState:
    device: str = ""
    protocol: str = ""
    receive_only: bool = False
    ready: bool = False
    vfo_limits: tuple[int, int] = (0, 0)
    if_limits: tuple[int, int] = (0, 0)
    modulations: list[str] = field(default_factory=list)
    audio_sample_rate: int = 48000
    vfo: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 0})   # channel -> Hz
    mode: str = ""
    filter_lo: int = 0
    filter_hi: int = 0
    agc: str = ""
    rit_enable: bool = False
    rit_offset: int = 0
    split: bool = False
    lock: bool = False
    rx_enable: bool = True
    tx_enable: bool = True
    drive: int = 0
    trx: bool = False
    smeter_dbm: float = -140.0
    tx_sensors: tuple[float, ...] = ()

    @property
    def freq(self) -> int:
        return self.vfo.get(0, 0)

    def apply(self, c: Command) -> str | None:
        """Update from one command; return the changed field name (or None if unknown)."""
        n = c.name
        if n == "protocol":
            self.protocol = ",".join(c.args)
        elif n == "device":
            self.device = c.str(0)
        elif n == "receive_only":
            self.receive_only = c.bool(0)
        elif n == "vfo_limits":
            self.vfo_limits = (c.int(0), c.int(1))
        elif n == "if_limits":
            self.if_limits = (c.int(0), c.int(1))
        elif n == "modulations_list":
            self.modulations = [a for a in c.args if a]
        elif n == "audio_samplerate":
            self.audio_sample_rate = c.int(0, 48000)
        elif n == "vfo" and c.int(0) == 0:                     # vfo:rx,channel,hz
            self.vfo[c.int(1)] = c.int(2)
        elif n == "modulation" and c.int(0) == 0:
            self.mode = c.str(1).lower()
        elif n == "rx_filter_band" and c.int(0) == 0:
            self.filter_lo, self.filter_hi = c.int(1), c.int(2)
        elif n == "agc_mode" and c.int(0) == 0:
            self.agc = c.str(1).lower()
        elif n == "rit_enable" and c.int(0) == 0:
            self.rit_enable = c.bool(1)
        elif n == "rit_offset" and c.int(0) == 0:
            self.rit_offset = c.int(1)
        elif n == "split_enable" and c.int(0) == 0:
            self.split = c.bool(1)
        elif n == "lock" and c.int(0) == 0:
            self.lock = c.bool(1)
        elif n == "rx_enable" and c.int(0) == 0:
            self.rx_enable = c.bool(1)
        elif n == "tx_enable" and c.int(0) == 0:
            self.tx_enable = c.bool(1)
        elif n == "drive":                                      # radio sends drive:rx,value
            self.drive = c.int(1) if len(c.args) > 1 else c.int(0)
        elif n == "trx" and c.int(0) == 0:
            self.trx = c.bool(1)
        elif n == "rx_smeter" and c.int(0) == 0:                # rx_smeter:rx,channel,dbm
            self.smeter_dbm = c.float(2, self.smeter_dbm)
        elif n == "tx_sensors" and c.int(0) == 0:
            self.tx_sensors = tuple(c.float(i) for i in range(1, len(c.args)))
        elif n == "ready":
            self.ready = True
        else:
            return None
        return {"vfo": "vfo", "modulation": "mode", "rx_filter_band": "filter",
                "agc_mode": "agc", "rx_smeter": "smeter", "ready": "ready"}.get(n, n)
