"""Aggregates decoded frames into a battery state snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
import time

from . import protocol as p


@dataclass
class ModuleState:
    index: int
    cells_mv: list[int | None] = field(default_factory=lambda: [None] * p.CELLS_PER_MODULE)
    temps_c: list[int | None] = field(default_factory=lambda: [None] * p.TEMPS_PER_MODULE)
    voltage_v: float | None = None
    status_raw: str | None = None
    summary_byte2: int | None = None
    balance_state_raw: str | None = None
    version_records: dict[int, str] = field(default_factory=dict)
    last_seen: float = 0.0

    @property
    def cells_known(self) -> list[int]:
        return [c for c in self.cells_mv if c is not None]

    def as_dict(self) -> dict:
        cells = self.cells_known
        d = {
            "module": self.index + 1,
            "cells_mv": self.cells_mv,
            "temps_c": self.temps_c,
            "voltage_v": self.voltage_v,
            "cell_min_mv": min(cells) if cells else None,
            "cell_max_mv": max(cells) if cells else None,
            "cell_min_index": self.cells_mv.index(min(cells)) + 1 if cells else None,
            "cell_max_index": self.cells_mv.index(max(cells)) + 1 if cells else None,
            "cell_avg_mv": round(sum(cells) / len(cells), 1) if cells else None,
            "cell_delta_mv": max(cells) - min(cells) if cells else None,
            "temp_max_c": max((t for t in self.temps_c if t is not None), default=None),
            "status_raw": self.status_raw,
            "summary_byte2": self.summary_byte2,
            "balance_state_raw": self.balance_state_raw,
            "version": " ".join(self.version_records[k] for k in sorted(self.version_records)) or None,
            "last_seen": self.last_seen,
        }
        return d


@dataclass
class BatteryState:
    modules: dict[int, ModuleState] = field(default_factory=dict)
    reference_cell_mv: int | None = None
    system_records: dict[int, str] = field(default_factory=dict)
    frames_total: int = 0
    last_frame: float = 0.0

    def _module(self, idx: int) -> ModuleState:
        if idx not in self.modules:
            self.modules[idx] = ModuleState(idx)
        return self.modules[idx]

    def update(self, f: p.Frame) -> None:
        if not f.extended:
            return
        self.frames_total += 1
        self.last_frame = f.timestamp or time.time()
        d = f.data

        # system unit 0xE8 -> 0xF4
        if f.src == 0xE8 and f.dest == 0xF4:
            if f.pf == p.PF_SYSTEM_RECORD and len(d) >= 3:
                self.system_records[d[0]] = d[1:].hex()
            return

        # master -> slave
        if f.src == p.MASTER_ADDR:
            if f.pf == p.PF_MASTER_TO_SLAVE_REF and len(d) >= 4:
                self.reference_cell_mv = int.from_bytes(d[2:4], "big")
            return

        # slave -> master
        if f.dest != p.MASTER_ADDR:
            return
        idx = p.module_index(f.src)
        if idx is None:
            return
        m = self._module(idx)
        m.last_seen = self.last_frame
        if f.pf == p.PF_CELL_VOLTAGES and len(d) >= 4:
            start = d[0] - 1
            for k in range((len(d) - 2) // 2):
                c = start + k
                if 0 <= c < p.CELLS_PER_MODULE:
                    m.cells_mv[c] = int.from_bytes(d[2 + 2 * k:4 + 2 * k], "big")
        elif f.pf == p.PF_TEMPERATURES and len(d) >= 2 + p.TEMPS_PER_MODULE:
            m.temps_c = [x - p.TEMP_OFFSET for x in d[2:2 + p.TEMPS_PER_MODULE]]
        elif f.pf == p.PF_MODULE_SUMMARY and len(d) >= 6:
            m.voltage_v = int.from_bytes(d[4:6], "big") / 10
            m.summary_byte2 = d[2]
        elif f.pf == p.PF_SLAVE_STATUS:
            m.status_raw = d.hex()
        elif f.pf == p.PF_SLAVE_BALANCE_STATE:
            m.balance_state_raw = d.hex()
        elif f.pf == p.PF_SLAVE_VERSION and len(d) >= 4:
            m.version_records[d[1]] = d[1:4].hex()

    def as_dict(self) -> dict:
        mods = [self.modules[k].as_dict() for k in sorted(self.modules)]
        cells = [(m["module"], i + 1, v) for m in mods for i, v in enumerate(m["cells_mv"]) if v is not None]
        temps = [t for m in mods for t in m["temps_c"] if t is not None]
        system: dict = {
            "module_count": len(mods),
            "cell_count": len(cells),
            "pack_voltage_v": round(sum(c[2] for c in cells) / 1000, 2) if cells else None,
            "reference_cell_mv": self.reference_cell_mv,
            "temp_min_c": min(temps) if temps else None,
            "temp_max_c": max(temps) if temps else None,
            "system_records_raw": {f"{k:02x}": v for k, v in sorted(self.system_records.items())},
        }
        if cells:
            lo = min(cells, key=lambda c: c[2])
            hi = max(cells, key=lambda c: c[2])
            avg = sum(c[2] for c in cells) / len(cells)
            system.update(
                cell_min_mv=lo[2], cell_min_module=lo[0], cell_min_cell=lo[1],
                cell_max_mv=hi[2], cell_max_module=hi[0], cell_max_cell=hi[1],
                cell_avg_mv=round(avg, 1), cell_delta_mv=hi[2] - lo[2],
            )
            for m in mods:
                m["deviation_from_pack_avg_mv"] = (
                    round(m["cell_avg_mv"] - avg, 1) if m["cell_avg_mv"] is not None else None
                )
                m["min_cell_below_pack_avg_mv"] = (
                    round(avg - m["cell_min_mv"], 1) if m["cell_min_mv"] is not None else None
                )
        return {"system": system, "modules": mods, "frames_total": self.frames_total, "timestamp": self.last_frame}
