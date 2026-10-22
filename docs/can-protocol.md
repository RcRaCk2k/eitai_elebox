# ELEBOX-HV internal CAN protocol (reverse engineered)

There is no vendor documentation. Everything here was derived from listen-only captures of one
ELEBOX-HV with 10 modules × 16 LiFePO4 cells (firmware records `118109 128909 139101`) on a
Growatt SPH 10000TL3 BH-UP, compared with the inverter's battery data over several charge/discharge cycles.
Each field carries a confidence level:

| Level | Meaning |
|---|---|
| **confirmed** | checked against an independent measurement |
| **likely** | consistent over all captures, plausible, not independently checked |
| **raw** | seen, meaning unknown; published raw so others can help |

> ⚠️ **Listen-only.** The bus is the BMS's internal link. Open the adapter in listen-only mode and never send.
> An active node acknowledges frames and can disturb the master-slave timing.

## Bus

- 250 kbit/s, 29-bit extended IDs only (the decoder ignores standard frames).
- J1939-like layout `0x18 | PF | destination | source`.
- Addresses: master BMS `0xF5`, module slaves `0x80 + n` (module 1 = `0x80`), system unit `0xE8`
  sending to `0xF4`. Which physical module in the stack has which address is not known yet.
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
| `1815F5xx` | slave → master | 790 ms | 8 | status, constant | raw |
| `1816F5xx` | slave → master | 260 ms | 6 | 3 rotating version records | likely |
| `1819F5xx` | slave → master | 790 ms | 6 | module voltage + one unknown byte | voltage confirmed |
| `1833F5xx` | slave → master | 3.4 s | 0 | empty reply to `1832` | likely |
| `1841F5xx` | slave → master | 790 ms | 8 | balancing state, always zero | raw |
| `1810xxF5` | master → slave | 790 ms | 8 | reference cell voltage | likely |
| `1832xxF5` | master → slave | 3.4 s | 8 | poll / keep-alive | raw |
| `1840xxF5` | master → slave | 790 ms | 8 | balancing command, constant | raw |
| `1833F4E8` | `0xE8` → `0xF4` | 160 ms | 6 / 7 | indexed system records `07`…`0C` | `07` SOC confirmed, rest raw |
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

### `1815` status — raw

Always `00 01 00 00 00 00 00 00` on every module.

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
| 0–1 | `01 00` | raw |
| 2 | 235…241, differs slightly between modules and over time (published as `summary_byte2`) | raw |
| 3 | `00` | raw |
| 4–5 | module voltage, 0.1 V (matches the sum of `1811`) | confirmed |

### `1833F5xx` — likely

DLC 0, sent by every slave right after the master's `1832` poll.

### `1841` balancing state — raw

Always `00…00` on every module in every capture, including the end of charge with the highest cell at
3476 mV and a cell spread of > 100 mV. The integration reports non-zero as `balancing` = on; that
mapping is an assumption until a non-zero frame is seen.

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

### `1833F4E8` system records

Byte 0 = record index, bytes 1–2 = `05 00` in every record. The records cycle every ~160 ms.

| Record | DLC | Bytes 3… | Observations | Confidence |
|---|---|---|---|---|
| `07` | 7 | 3–5: 24-bit value, 6: **SOC %** | SOC equals the SOC the inverter reports. Bytes 3–5 stayed constant over a whole day and night (`03 FD CE` on 18 Oct) but had changed four days later (`03 FF FC`). | SOC confirmed, 3–5 raw |
| `08` | 6 | 3–5: 24-bit counter | steps by 1, only while discharging, faster at high power | raw |
| `09` | 6 | 3–5: 24-bit counter | constant during a discharge-only night, rose on days with charging (+2830 while the inverter counted 44.5 kWh charged) | raw |
| `0A` | 6 | 3–5: 24-bit counter | steps by 10, only while discharging | raw |
| `0B` | 6 | 3–5 | `00 00 00` most of the time, `14 00 64` in one capture | raw |
| `0C` | 6 | 3: like `08`, 4–5: like `0A` | both start at zero when the BMS starts | raw |

The ratios of `08`, `09`, `0A` to the inverter's kWh counters are not constant, so they are probably not
plain energy or charge counters.

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
| no balancing reported | `1841` zero (4 days of live data), `1840` unchanged (all captures and live samples) | since 18 Oct |

## Open questions

- Meaning of `1810` bytes 4–5, `1819` byte 2, `1815`, `1832`, records `07` bytes 3–5, `08`…`0C`.
- What `1840` / `1841` look like when the BMS balances, and at which cell voltage it starts.
- Mapping of slave addresses to physical module positions.
- Contents of `1814` when an alarm is active.

Captures under other conditions (alarm, balancing, other firmware, other module counts) are very welcome:
open an issue with the `inventory` JSON or a `candump -L` log.
