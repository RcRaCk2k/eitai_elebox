# ELEBOX-HV internal CAN protocol (reverse engineered)

There is no public vendor documentation. Everything here was derived from listen-only captures of one
ELEBOX-HV with 10 modules × 16 LiFePO4 cells (firmware records `118109 128909 139101`) on a
Growatt SPH 10000TL3 BH-UP, compared with the inverter's battery data over several charge/discharge cycles.
Since 0.4.0 it also uses how the BMS maker's Windows service tool (EVBMSSoft 2.60, supplied by EITAI support for
diagnostics) interprets the frames: its receive routine was examined statically, nothing of it is included here.
Each field carries a confidence level:

| Level | Meaning |
|---|---|
| **confirmed** | checked against an independent measurement |
| **vendor** | meaning and scaling as the vendor tool decodes it; consistent with our captures |
| **likely** | consistent over all captures, plausible, not independently checked |
| **raw** | seen, meaning unknown; published raw so others can help |

In the vendor tool's terms the master is an *EVBCM*, a module slave an *EVBMM*; the PC tool uses address `0xF4`
and expects the master at `0xE8` in energy-storage systems.

> ⚠️ **Listen-only.** The bus is the BMS's internal link. Open the adapter in listen-only mode and never send.
> An active node acknowledges frames and can disturb the master-slave timing.

## Bus

- 250 kbit/s, 29-bit extended IDs only (the decoder ignores standard frames).
- J1939-like layout `0x18 | PF | destination | source`.
- Addresses: master BMS `0xF5` towards the modules, module slaves `0x80 + n` (module 1 = `0x80`, vendor),
  and the master again as `0xE8` sending system records to `0xF4`, the PC tool's address (vendor).
  Which physical module in the stack has which address is not known yet.
- With 10 modules exactly **112 IDs** are on the bus: 11 message types per module plus 2 system IDs.
  Full captures so far were taken at rest; during charge and discharge only the decoded values were logged.
  Since bridge 0.3.0 every ID is counted continuously: the bridge publishes everything it sees on `eitai_elebox/<device_id>/inventory`
  ([MQTT format](mqtt-format.md)) and logs any ID outside this list.

## Overview

| ID | Direction | Period | DLC | Content | Confidence |
|---|---|---|---|---|---|
| `1811F5xx` | slave → master | 130 ms | 8 / 4 | cell voltages | confirmed |
| `1812F5xx` | slave → master | 790 ms | 6 | 4 temperatures | likely |
| `1814F5xx` | slave → master | 790 ms | 0 | always empty (alarms?) | raw |
| `1815F5xx` | slave → master | 790 ms | 8 | passive balancing per cell | vendor |
| `1816F5xx` | slave → master | 260 ms | 6 | 3 rotating version records | likely |
| `1819F5xx` | slave → master | 790 ms | 6 | supply voltage, module voltage | voltage confirmed, rest vendor |
| `1833F5xx` | slave → master | 3.4 s | 0 | empty reply to `1832` | likely |
| `1841F5xx` | slave → master | 790 ms | 8 | module fault bits, always zero | vendor |
| `1810xxF5` | master → slave | 790 ms | 8 | reference cell voltage | likely |
| `1832xxF5` | master → slave | 3.4 s | 8 | poll / keep-alive | raw |
| `1840xxF5` | master → slave | 790 ms | 8 | balancing command, constant | raw |
| `1833F4E8` | `0xE8` → `0xF4` | 160 ms | 6 / 7 | SOC, charge/discharge Ah and kWh counters | SOC confirmed, counters vendor |
| `183DF4E8` | `0xE8` → `0xF4` | 26 ms | 8 | forwards the module version records | likely |

`xx` = slave address `0x80`…`0x89`. Byte numbers below are 0-based, multi-byte values big endian.

## Slave → master

### `1811` cell voltages — confirmed

| Byte | Content |
|---|---|
| 0 | number of the first cell in this frame (1-based): `01`, `04`, `07`, `0A`, `0D`, `10` |
| 1 | `00` |
| 2–7 | up to 3 cell voltages, mV, uint16 |

Six frames cover the 16 cells; the frame for cell 16 has DLC 4. The sum of the 16 cells matches `1819`
(module voltage), and the sum over all modules matches the pack voltage reported by the inverter within ≈ 1 V.

### `1812` temperatures — likely

| Byte | Content |
|---|---|
| 0–1 | `01 00` |
| 2–5 | 4 temperatures, raw − 40 = °C (seen: ≈ 28…35 °C, matches the inverter's battery temperature) |

### `1814` — raw

Always DLC 0. Name `PF_SLAVE_ALARMS` is a guess (an alarm frame that carries data only when something is wrong).

### `1815` balancing state — vendor

| Byte | Content |
|---|---|
| 0 | record, `00` |
| 1 | `01` (low nibble is a sub-record for other module types) |
| 2–3 | passive balancing bitmap, uint16: bit 0 = cell 1 … bit 15 = cell 16, 1 = balancing resistor on |
| 4–7 | `00` |

That is how the vendor tool decodes record `00` for passive 16-cell modules (EVBMM-1612). Record `01` is used by
actively balancing module types and was never seen here. On this battery the frame was
`00 01 00 00 00 00 00 00` on every module in every capture and live sample, including the end of charge with the
highest cell at 3476 mV and a cell spread of > 100 mV: **no cell was balanced**.

### `1816` version records — likely

| Byte | Content |
|---|---|
| 0 | `00` |
| 1 | record number `11`, `12`, `13` (rotating) |
| 2–3 | record data, e.g. `81 09`, `89 09`, `91 01` |
| 4–5 | `00 00` |

The integration shows bytes 1–3 of the three records as the module version, e.g. `118109 128909 139101`.

### `1819` module summary — module voltage confirmed

| Byte | Content | Confidence |
|---|---|---|
| 0 | record, `01` | vendor |
| 1–2 | module supply voltage, 0.1 V; seen 23.5…24.1 V (`supply_voltage_v`) | vendor |
| 3 | a temperature, raw − 40 = °C; always `00` here, so probably not fitted | vendor |
| 4–5 | module voltage, 0.1 V (matches the sum of `1811`) | confirmed |

### `1833F5xx` — likely

DLC 0, sent by every slave right after the master's `1832` poll.

### `1841` fault bits — vendor

Bit *n* = byte *n* / 8, bit *n* % 8 for bits 0–23; bit 24 = byte 3 bit 4; bits 25–26 = byte 4 bits 0–1
(the vendor tool evaluates the last two only for some projects).

| Bit | Fault |
|---|---|
| 0 / 1 | module supply under- / overvoltage |
| 2 / 3 | balancer supply under- / overvoltage |
| 4 / 5 | balancer board / balancer board supply |
| 6 / 7 | balancing detection / balancing direction |
| 8–11 | balancer board 1–4 |
| 12–15 | balancing detection 1–4 |
| 16–19 | balancing direction 1–4 |
| 20–23 | measurement chip 1–4 |
| 24 | passive balancing fault |
| 25 / 26 | temperature wire shorted to ground or open / shorted or open |

Always `00…00` on every module in every capture: no module, including module 6, reports a fault.
Up to 0.3.0 this frame was wrongly published as the balancing state.

## Master → slave

### `1810` reference — likely

| Byte | Content |
|---|---|
| 0–1 | `FF FF` |
| 2–3 | reference cell voltage, mV: equals the pack's average cell voltage (published as `reference_cell_mv`) |
| 4–5 | `3E 80` = 16000, constant (a limit or set point?) |
| 6–7 | `FF FF` |

### `1832` poll — raw

Byte 0 alternates `01` / `02`, byte 1 is `00` or `01`, rest zero. Every 3.4 s per slave; the slave answers with an
empty `1833F5xx`.

### `1840` balancing command — raw

Always `01 00 00 00 00 00 00 00` in every capture and live sample checked so far.

## System unit `0xE8` → `0xF4`

### `1833F4E8` system records — vendor

Byte 0 = record index, byte 1 = `05` (record type: pack data; other types carry per-cell values and were not
seen here). Values are big endian. The records cycle every ~160 ms.
The vendor tool reads the index as 6 × pack + field, so `07`…`0C` are fields 1…6 of pack 1.

| Record | DLC | Content | Confidence |
|---|---|---|---|
| `07` | 7 | bytes 2–5: total charged capacity, 0.1 Ah; byte 6: **SOC %** | SOC confirmed, Ah vendor |
| `08` | 6 | bytes 2–5: total discharged capacity, 0.1 Ah | vendor |
| `09` | 6 | bytes 2–5: total charged energy, 0.01 kWh | vendor |
| `0A` | 6 | bytes 2–5: total discharged energy, 0.01 kWh | vendor |
| `0B` | 6 | bytes 2–3: capacity of the current charge, 0.1 Ah; bytes 4–5: its energy, 0.01 kWh | vendor |
| `0C` | 6 | bytes 2–3: capacity of the current discharge, 0.1 Ah; bytes 4–5: its energy, 0.01 kWh | vendor |

Consistent with the captures: `08` steps by 1 (0.1 Ah) and `0A` by 10 (0.1 kWh) only while discharging,
`09` rises only on days with charging; `0B` = `00 14 00 64` = 2.0 Ah / 1.00 kWh and `0C` = `00 1B 00 82` =
2.7 Ah / 1.30 kWh, both matching the pack voltage of ≈ 520 V. The BMS counts less than the inverter
(e.g. +28.3 kWh charged while the inverter counted 44.5 kWh), and its discharge totals are far below its charge
totals (13 156 / 3 700 kWh on 23 Oct 2026). It probably misses small currents (see below); whether the
discharge counters were reset at some point is unknown.

### `183DF4E8` version forward — likely

Byte 0 = module number (1…10), bytes 1–3 = the module's `1816` record (bytes 1–3), rest zero. Cycles through all
modules and records (30 combinations) every ~0.8 s.

## Not on this bus

- **Pack current.** No field found that follows the battery current. The BMS reports it to the inverter on a
  separate link; read it from the inverter instead.
- Pack SOH, cycle count, charge/discharge limits: also only on the inverter link as far as we know.

## Observed BMS behaviour

Measured from cell voltages (this bus) together with the inverter data. Useful for interpreting the values,
not part of the frame format.

| Observation | Value | Seen |
|---|---|---|
| SOC jumps to 0 % when the lowest cell reaches, at rest | ≈ 3030 mV | 2 nights, ±1 mV |
| SOC jumps to 99–100 % when the highest cell reaches, while charging | ≈ 3470–3476 mV | 2 charges |
| charging ends at that point, average cell voltage | ≈ 3395–3415 mV under charge, ≈ 3330 mV at rest | 2 charges |
| currents below ≈ 0.8 A seem not to be counted | SOC stays at 0 % for hours at 0.55 A charge, jumps to 12–20 % once the current exceeds ≈ 0.8 A | 2 mornings |
| SOC is also corrected gradually | e.g. −18 % within 50 min while ≈ 1.5 % was discharged | 1 night |
| no balancing | `1815` balancing bitmap zero, `1840` unchanged (all captures and live samples) | since 18 Oct |
| no module faults | `1841` zero (4 days of live data) | since 18 Oct |

## Open questions

- Meaning of `1810` bytes 4–5, `1832` and `1840` (what the master sends to the modules).
- At which cell voltage or spread the BMS starts balancing, and whether it ever does on this firmware.
- Mapping of slave addresses to physical module positions.
- Contents of `1814` (not evaluated by the vendor tool either).

Captures under other conditions (alarm, balancing, other firmware, other module counts) are very welcome:
open an issue with the `inventory` JSON or a `candump -L` log.
