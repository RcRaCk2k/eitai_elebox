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

Full byte-level description, open questions and observed BMS behaviour: **[docs/can-protocol.md](docs/can-protocol.md)**.

29-bit IDs, layout `0x18 | type | destination | source`. Master BMS `0xF5`, module slaves `0x80 + n`,
system unit `0xE8` → `0xF4`. With 10 modules the bus carries exactly 112 IDs:

| ID | Direction | Period | Content | Confidence |
|---|---|---|---|---|
| `1811F5xx` | slave → master | 130 ms | cell voltages, mV | confirmed |
| `1812F5xx` | slave → master | 790 ms | 4 temperatures, raw − 40 = °C | likely |
| `1819F5xx` | slave → master | 790 ms | module voltage, 0.1 V; byte 2 unknown | voltage confirmed |
| `1816F5xx` | slave → master | 260 ms | module version records | likely |
| `1814F5xx` | slave → master | 790 ms | always empty | raw |
| `1815F5xx` | slave → master | 790 ms | status, always `0001000000000000` | raw |
| `1841F5xx` | slave → master | 790 ms | balancing state, always zero so far | raw |
| `1833F5xx` | slave → master | 3.4 s | empty reply to `1832` | likely |
| `1810xxF5` | master → slave | 790 ms | reference cell voltage (= pack average), mV | likely |
| `1832xxF5` | master → slave | 3.4 s | poll | raw |
| `1840xxF5` | master → slave | 790 ms | balancing command, always `0100000000000000` | raw |
| `1833F4E8` | `0xE8` → `0xF4` | 160 ms | system records `07`…`0C`: `07` byte 6 = SOC %, the rest are counters of unknown meaning | SOC confirmed |
| `183DF4E8` | `0xE8` → `0xF4` | 26 ms | forwards the module version records | likely |

Pack current is not on this bus. The bridge counts every ID it sees and publishes the list on
`…/inventory`, so new or changing frames show up without a separate capture.

## Development

```sh
cd lib && PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## License

MIT
