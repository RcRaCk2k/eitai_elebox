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
    supply_voltage_v: float | None = None
    balance_raw: str | None = None
    balancing_cells: list[int] | None = None
    fault_raw: str | None = None
    faults: list[str] | None = None
    balance_cmd_raw: str | None = None
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
            "supply_voltage_v": self.supply_voltage_v,
            "balance_raw": self.balance_raw,
            "balancing_cells": self.balancing_cells,
            "balancing": bool(self.balancing_cells) if self.balancing_cells is not None else None,
            "fault_raw": self.fault_raw,
            "faults": self.faults,
            "fault": bool(self.faults) if self.faults is not None else None,
            "balance_cmd_raw": self.balance_cmd_raw,
            "version": " ".join(self.version_records[k] for k in sorted(self.version_records)) or None,
            "last_seen": self.last_seen,
        }
        return d


MAX_VARIANTS = 32  # distinct payloads kept per CAN ID in the inventory


@dataclass
class IdStats:
    """Everything seen for one CAN ID, decoded or not: the base for further reverse engineering."""
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    last_data: str = ""
    variants: dict[str, int] = field(default_factory=dict)
    variants_overflow: bool = False

    def add(self, data: str, ts: float) -> None:
        if not self.count:
            self.first_seen = ts
        self.count += 1
        self.last_seen = ts
        self.last_data = data
        if data in self.variants:
            self.variants[data] += 1
        elif len(self.variants) < MAX_VARIANTS:
            self.variants[data] = 1
        else:
            self.variants_overflow = True


@dataclass
class BatteryState:
    modules: dict[int, ModuleState] = field(default_factory=dict)
    reference_cell_mv: int | None = None
    system_records: dict[int, str] = field(default_factory=dict)
    frames_total: int = 0
    last_frame: float = 0.0
    ids: dict[int, IdStats] = field(default_factory=dict)

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
        self.ids.setdefault(f.can_id, IdStats()).add(d.hex(), self.last_frame)

        # master's system records 0xE8 -> 0xF4
        if f.src == p.SYSTEM_ADDR and f.dest == p.SYSTEM_DEST:
            if f.pf == p.PF_SYSTEM_RECORD and len(d) >= 3:
                self.system_records[d[0]] = d[1:].hex()
            return

        # master -> slave
        if f.src == p.MASTER_ADDR:
            if f.pf == p.PF_MASTER_TO_SLAVE_REF and len(d) >= 4:
                self.reference_cell_mv = int.from_bytes(d[2:4], "big")
            elif f.pf == p.PF_MASTER_BALANCE_CMD:
                idx = p.module_index(f.dest)
                if idx is not None:
                    self._module(idx).balance_cmd_raw = d.hex()
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
            m.supply_voltage_v = int.from_bytes(d[1:3], "big") / 10
        elif f.pf == p.PF_SLAVE_BALANCE_STATE:
            cells = p.balancing_cells(d)
            if cells is not None:
                m.balance_raw = d.hex()
                m.balancing_cells = cells
        elif f.pf == p.PF_SLAVE_FAULTS:
            m.fault_raw = d.hex()
            m.faults = p.slave_faults(d)
        elif f.pf == p.PF_SLAVE_VERSION and len(d) >= 4:
            m.version_records[d[1]] = d[1:4].hex()

    def _decoded_records(self) -> dict:
        out: dict = {}
        rec = self.system_records
        if len(rec.get(p.REC_STATUS, "")) >= 12:
            out["soc_pct"] = bytes.fromhex(rec[p.REC_STATUS])[5]
        # stored without the index byte: [05, value...]
        for k, (name, scale) in p.REC_TOTALS.items():
            if len(rec.get(k, "")) >= 10:
                out[name] = round(int.from_bytes(bytes.fromhex(rec[k])[1:5], "big") * scale, 2)
        for k, name in p.REC_CURRENT.items():
            if len(rec.get(k, "")) >= 10:
                v = bytes.fromhex(rec[k])
                out[f"{name}_ah_current"] = round(int.from_bytes(v[1:3], "big") * 0.1, 1)
                out[f"{name}_kwh_current"] = round(int.from_bytes(v[3:5], "big") * 0.01, 2)
        return out

    def inventory(self) -> list[dict]:
        """All CAN IDs seen so far with frame count, mean period and distinct payloads."""
        out = []
        for can_id in sorted(self.ids):
            st = self.ids[can_id]
            period = (st.last_seen - st.first_seen) / (st.count - 1) if st.count > 1 else None
            out.append({
                "id": f"{can_id:08X}",
                "known": p.is_known(can_id),
                "count": st.count,
                "period_ms": round(period * 1000) if period is not None else None,
                "last_data": st.last_data,
                "variants": len(st.variants),
                "variants_overflow": st.variants_overflow,
                # the full list only for IDs with few payloads; cell voltages etc. change all the time
                "payloads": st.variants if len(st.variants) <= 8 else None,
            })
        return out

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
            **self._decoded_records(),
        }
        if cells:
            lo = min(cells, key=lambda c: c[2])
            hi = max(cells, key=lambda c: c[2])
            avg = sum(c[2] for c in cells) / len(cells)
            system.update(
                cell_min_mv=lo[2], cell_min_module=lo[0], cell_min_cell=lo[1],
                cell_max_mv=hi[2], cell_max_module=hi[0], cell_max_cell=hi[1],
                cell_avg_mv=round(avg, 1), cell_delta_mv=hi[2] - lo[2],
                cell_min_below_avg_mv=round(avg - lo[2], 1),
            )
            for m in mods:
                m["deviation_from_pack_avg_mv"] = (
                    round(m["cell_avg_mv"] - avg, 1) if m["cell_avg_mv"] is not None else None
                )
                m["min_cell_below_pack_avg_mv"] = (
                    round(avg - m["cell_min_mv"], 1) if m["cell_min_mv"] is not None else None
                )
        return {"system": system, "modules": mods, "frames_total": self.frames_total, "timestamp": self.last_frame}
