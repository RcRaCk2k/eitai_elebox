"""CAN frame sources. Every source is strictly listen-only: it never drives the bus.

Background: a node in normal mode with the wrong bitrate sends error frames on every
frame it cannot decode. On the ELEBOX-HV this made the BMS disconnect the battery.
Listen-only mode sends no ACKs and no error frames, so it cannot disturb the bus.
"""
from __future__ import annotations

import ctypes as C
import json
import logging
import socket
import struct
import subprocess
import time
from collections.abc import Iterator

from eitai_elebox import BITRATE, Frame

_LOG = logging.getLogger(__name__)


class ZlgSource:
    """ZLG USBCAN-I/II compatible adapters (USB 0471:1200) via the vendor libusbcan.so.

    The library is proprietary and must be obtained from ZLG by the user.
    """

    DEVICE_TYPE = 4  # VCI_USBCAN2, also used by single-channel USBCAN-I clones
    MODE_LISTEN_ONLY = 1
    TIMINGS = {250_000: (0x01, 0x1C), 500_000: (0x00, 0x1C), 125_000: (0x03, 0x1C)}

    class _Init(C.Structure):
        _fields_ = [("AccCode", C.c_uint), ("AccMask", C.c_uint), ("Reserved", C.c_uint),
                    ("Filter", C.c_ubyte), ("Timing0", C.c_ubyte), ("Timing1", C.c_ubyte), ("Mode", C.c_ubyte)]

    class _Obj(C.Structure):
        _fields_ = [("ID", C.c_uint), ("TimeStamp", C.c_uint), ("TimeFlag", C.c_ubyte), ("SendType", C.c_ubyte),
                    ("Remote", C.c_ubyte), ("Extern", C.c_ubyte), ("DataLen", C.c_ubyte),
                    ("Data", C.c_ubyte * 8), ("Res", C.c_ubyte * 3)]

    def __init__(self, lib_path: str, device_index: int = 0, channel: int = 0, bitrate: int = BITRATE):
        self._lib = C.CDLL(lib_path)
        self._dev, self._ch = device_index, channel
        self._timing = self.TIMINGS[bitrate]
        self._buf = (self._Obj * 2500)()

    def _open(self) -> bool:
        lib, dt = self._lib, self.DEVICE_TYPE
        lib.VCI_CloseDevice(dt, self._dev)
        if lib.VCI_OpenDevice(dt, self._dev, 0) != 1:
            return False
        cfg = self._Init(0, 0xFFFFFFFF, 0, 1, *self._timing, self.MODE_LISTEN_ONLY)
        return (lib.VCI_InitCAN(dt, self._dev, self._ch, C.byref(cfg)) == 1
                and lib.VCI_StartCAN(dt, self._dev, self._ch) == 1)

    def frames(self) -> Iterator[Frame | None]:
        """Yield frames; yields None periodically when idle so callers can do housekeeping."""
        while not self._open():
            _LOG.warning("ZLG adapter not available, retrying in 5 s")
            time.sleep(5)
        _LOG.info("ZLG adapter opened (listen-only, %d bit/s)", BITRATE)
        last_rx = time.time()
        while True:
            n = self._lib.VCI_Receive(self.DEVICE_TYPE, self._dev, self._ch, self._buf, 2500, 100)
            now = time.time()
            if n == 0xFFFFFFFF or n == 0:
                if now - last_rx > 30:
                    _LOG.warning("no frames for 30 s, reopening adapter")
                    while not self._open():
                        time.sleep(5)
                    last_rx = now
                yield None
                continue
            last_rx = now
            for i in range(n):
                m = self._buf[i]
                yield Frame(m.ID, bytes(m.Data[:m.DataLen]), now, bool(m.Extern))


class SocketCanSource:
    """Any Linux SocketCAN adapter. The interface must be configured listen-only, e.g.:

        ip link set can0 type can bitrate 250000 listen-only on && ip link set can0 up
    """

    _FMT = "<IB3x8s"
    _EFF_FLAG, _EFF_MASK = 0x80000000, 0x1FFFFFFF

    def __init__(self, iface: str):
        self._iface = iface

    def _check_listen_only(self) -> None:
        out = subprocess.run(["ip", "-details", "-json", "link", "show", self._iface],
                             check=True, capture_output=True, text=True).stdout
        info = json.loads(out)[0].get("linkinfo", {}).get("info_data", {})
        if "LISTEN-ONLY" not in info.get("ctrlmode", []):
            raise RuntimeError(
                f"{self._iface} is not in listen-only mode. Refusing to start, an active node can "
                f"disturb the BMS bus. Run: ip link set {self._iface} type can bitrate {BITRATE} listen-only on")
        if info.get("bittiming", {}).get("bitrate") != BITRATE:
            _LOG.warning("%s bitrate is %s, ELEBOX-HV uses %d", self._iface,
                         info.get("bittiming", {}).get("bitrate"), BITRATE)

    def frames(self) -> Iterator[Frame | None]:
        self._check_listen_only()
        s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        s.bind((self._iface,))
        s.settimeout(1.0)
        _LOG.info("SocketCAN %s opened (listen-only)", self._iface)
        while True:
            try:
                raw = s.recv(16)
            except TimeoutError:
                yield None
                continue
            can_id, dlc, data = struct.unpack(self._FMT, raw)
            ext = bool(can_id & self._EFF_FLAG)
            yield Frame(can_id & (self._EFF_MASK if ext else 0x7FF), data[:dlc], time.time(), ext)


class ReplaySource:
    """Replays a `candump -L` log in real time, looping. For development without a battery."""

    def __init__(self, path: str):
        self._path = path

    def frames(self) -> Iterator[Frame | None]:
        from eitai_elebox import parse_candump_line

        while True:
            prev = None
            with open(self._path) as fh:
                for line in fh:
                    f = parse_candump_line(line)
                    if f is None:
                        continue
                    if prev is not None and f.timestamp > prev:
                        time.sleep(min(f.timestamp - prev, 1.0))
                        yield None
                    prev = f.timestamp
                    yield Frame(f.can_id, f.data, time.time(), f.extended)
