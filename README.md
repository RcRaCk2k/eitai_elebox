# EITAI ELEBOX-HV for Home Assistant

Monitor every cell of an **EITAI ELEBOX-HV** high-voltage LiFePO4 battery in Home Assistant:
160 cell voltages, 40 temperatures and per-module statistics for a 10-module system,
so a weak module or cell is visible at a glance.

> Unofficial project, not affiliated with EITAI. The CAN protocol was reverse engineered
> from captures; fields that are not understood yet are exposed as raw diagnostic sensors.

## How it works

```
ELEBOX-HV internal BMS bus ──CAN 250 kbit/s, listen-only──> bridge (Docker) ──MQTT──> Home Assistant integration
```

* **`lib/`** – `eitai-elebox`, a dependency-free protocol decoder with tests.
* **`bridge/`** – reads the bus and publishes snapshots to `eitai_elebox/<device_id>/{info,state,availability}`.
* **`custom_components/eitai_elebox/`** – the HACS integration. It is discovered automatically from the
  bridge's retained `info` topic and creates one system device plus one device per module.

## ⚠️ Listen-only is mandatory

The adapter is connected to the battery's **internal** bus between the master BMS and the module slaves.
A CAN node in normal mode with a wrong bitrate floods the bus with error frames; on an ELEBOX-HV this made
the BMS disconnect the battery from the inverter. The bridge therefore only ever opens the bus in
listen-only mode (no ACKs, no error frames) and refuses to start on a SocketCAN interface that is not
configured listen-only.

## Supported CAN adapters

| Adapter | Source | Notes |
|---|---|---|
| Any SocketCAN adapter (CANable/candleLight, PEAK, Waveshare, …) | `SOURCE=socketcan` | `ip link set can0 type can bitrate 250000 listen-only on && ip link set can0 up`, run the container with `network_mode: host` |
| ZLG USBCAN-I/II and clones (USB `0471:1200`, e.g. "iTEK USBCAN") | `SOURCE=zlg` | Requires ZLG's proprietary `libusbcan.so` (Linux x86_64, "usbcan_ii_libusb"), which is not distributed with this project. Put it at `zlg/libusbcan.so`. |
| Recorded `candump -L` log | `SOURCE=replay` | For development |

## Installation

### 1. Bridge

```sh
cp .env.example .env    # set SOURCE, MQTT_HOST/USER/PASSWORD (the broker Home Assistant uses)
docker compose up -d --build
```

### 2. Home Assistant integration

Add this repository to HACS as a custom repository (category *Integration*), install **EITAI ELEBOX-HV**
and restart Home Assistant. Requires the MQTT integration. The battery appears under
*Settings → Devices & services → Discovered* as soon as the bridge is running.

## Decoded protocol

29-bit IDs, layout `0x18 | type | destination | source`. Master BMS `0xF5`, module slaves `0x80 + n`.

| ID | Direction | Period | Content | Confidence |
|---|---|---|---|---|
| `1811F5xx` | slave → master | 130 ms | byte 0 = first cell (1-based), then up to 3 cell voltages, mV, big endian | confirmed |
| `1812F5xx` | slave → master | 790 ms | bytes 2–5 = 4 temperatures, raw − 40 = °C | very likely |
| `1819F5xx` | slave → master | 790 ms | bytes 4–5 = module voltage, 0.1 V (matches cell sum) | confirmed |
| `1810xxF5` | master → slave | 790 ms | bytes 2–3 = reference cell voltage, mV (equals pack average) | likely |
| `1815F5xx` | slave → master | 790 ms | module status, always `0001000000000000` so far | raw |
| `1840xxF5` | master → slave | 790 ms | balancing command, always `0100000000000000` so far | raw |
| `1841F5xx` | slave → master | 790 ms | balancing state, all zero (no balancing) in every capture so far | `balancing` = non-zero |
| `1816F5xx`, `183DF4E8` | | 260 ms | module version records (forwarded by `0xE8`) | likely |
| `1833F4E8` | `0xE8` → `0xF4` | 160 ms | indexed system records `07`…`0C`: `07` byte 6 = SOC %; `08`, `0A` bytes 3–5 = counters stepping during discharge; `0C` = the same counters since BMS start; `09`, `0B` constant | SOC decoded, rest raw |

## Development

```sh
cd lib && PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## License

MIT
