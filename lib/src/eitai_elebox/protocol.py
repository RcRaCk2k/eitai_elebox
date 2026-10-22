"""Decoder for the internal CAN bus of the EITAI ELEBOX-HV battery (250 kbit/s, 29-bit IDs).

The bus connects one master BMS (address 0xF5) with one slave per battery module
(addresses 0x80, 0x81, ...). A second unit (0xE8) sends system-level records to 0xF4.
IDs follow a J1939-like layout: 0x18 | PF | destination | source.

No vendor documentation exists; field meanings were derived from captures.
Every decoded field carries a confidence note in FIELDS below.
"""
from __future__ import annotations

from dataclasses import dataclass

BITRATE = 250_000
MASTER_ADDR = 0xF5
SLAVE_BASE_ADDR = 0x80
MAX_MODULES = 32
CELLS_PER_MODULE = 16
TEMPS_PER_MODULE = 4
TEMP_OFFSET = 40

# PF (message type) values
PF_MASTER_TO_SLAVE_REF = 0x10   # master -> slave, 8 bytes, bytes 2-3 = reference cell voltage (mV); see docs/can-protocol.md
PF_CELL_VOLTAGES = 0x11         # slave -> master, start cell + up to 3 cell voltages (mV, big endian)
PF_TEMPERATURES = 0x12          # slave -> master, 4 temperatures (raw - 40 = degC)
PF_SLAVE_ALARMS = 0x14          # slave -> master, empty in all captures so far
PF_SLAVE_STATUS = 0x15          # slave -> master, 8 bytes status, meaning unknown
PF_SLAVE_VERSION = 0x16         # slave -> master, 3 rotating version/info records
PF_MODULE_SUMMARY = 0x19        # slave -> master, bytes 4-5 = module voltage (0.1 V)
PF_MASTER_POLL = 0x32           # master -> slave, keep-alive poll
PF_SYSTEM_RECORD = 0x33         # 0xE8 -> 0xF4: indexed system records; slave -> master: empty reply to PF_MASTER_POLL
PF_SYSTEM_FORWARD = 0x3D        # 0xE8 -> 0xF4: forwards slave version records (byte 0 = module number)
PF_MASTER_BALANCE_CMD = 0x40    # master -> slave
PF_SLAVE_BALANCE_STATE = 0x41   # slave -> master, all zero while not balancing

# PF_SYSTEM_RECORD (0xE8 -> 0xF4), byte 0 = record index, bytes 1-2 = 05 00 in all records
REC_STATUS = 0x07               # byte 6 = state of charge in % (matches the SOC reported to the inverter)
REC_COUNTERS = (0x08, 0x0A)     # bytes 3-5 = 24-bit counters stepping during discharge, meaning unknown
# record 0x09 bytes 3-5 rise on days with charging and stay constant while only discharging; 0x0B and 0x0C vary too

# every (PF, direction) combination seen on the bus; anything else shows up as unknown in the inventory
SYSTEM_ADDR, SYSTEM_DEST = 0xE8, 0xF4
KNOWN_SLAVE_PFS = {PF_CELL_VOLTAGES, PF_TEMPERATURES, PF_SLAVE_ALARMS, PF_SLAVE_STATUS, PF_SLAVE_VERSION,
                   PF_MODULE_SUMMARY, PF_SYSTEM_RECORD, PF_SLAVE_BALANCE_STATE}
KNOWN_MASTER_PFS = {PF_MASTER_TO_SLAVE_REF, PF_MASTER_POLL, PF_MASTER_BALANCE_CMD}
KNOWN_SYSTEM_PFS = {PF_SYSTEM_RECORD, PF_SYSTEM_FORWARD}


@dataclass(frozen=True, slots=True)
class Frame:
    can_id: int
    data: bytes
    timestamp: float = 0.0
    extended: bool = True

    @property
    def pf(self) -> int:
        return (self.can_id >> 16) & 0xFF

    @property
    def dest(self) -> int:
        return (self.can_id >> 8) & 0xFF

    @property
    def src(self) -> int:
        return self.can_id & 0xFF


def is_known(can_id: int) -> bool:
    """True if the ID matches a message type documented in docs/can-protocol.md."""
    if can_id >> 24 != 0x18:
        return False
    pf, dest, src = (can_id >> 16) & 0xFF, (can_id >> 8) & 0xFF, can_id & 0xFF
    if src == SYSTEM_ADDR and dest == SYSTEM_DEST:
        return pf in KNOWN_SYSTEM_PFS
    if src == MASTER_ADDR and module_index(dest) is not None:
        return pf in KNOWN_MASTER_PFS
    if dest == MASTER_ADDR and module_index(src) is not None:
        return pf in KNOWN_SLAVE_PFS
    return False


def module_index(addr: int) -> int | None:
    """Return 0-based module index for a slave address, or None."""
    idx = addr - SLAVE_BASE_ADDR
    return idx if 0 <= idx < MAX_MODULES else None


def parse_candump_line(line: str) -> Frame | None:
    """Parse a `candump -L` style line: '(1700000000.123) can0 1811F580#0100...'."""
    parts = line.split()
    if len(parts) < 3 or "#" not in parts[2]:
        return None
    ts = float(parts[0].strip("()"))
    ident, data = parts[2].split("#", 1)
    return Frame(int(ident, 16), bytes.fromhex(data), ts, extended=len(ident) > 3)
