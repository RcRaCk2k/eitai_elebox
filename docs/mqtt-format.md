# MQTT format (schema 1)

Any publisher can feed the Home Assistant integration: the Docker bridge in this repository,
an ESP32 with a CAN transceiver, or anything else that reads the ELEBOX-HV bus **in listen-only mode**.

All topics live under `eitai_elebox/<device_id>/`. `<device_id>` is a free identifier
(`[a-z0-9_-]`), unique per battery; it becomes the Home Assistant unique ID.

| Topic | Retained | QoS | When |
|---|---|---|---|
| `…/info` | yes | 1 | after all modules reported, and whenever the topology changes |
| `…/state` | yes | 0 | periodically, recommended every 5–10 s |
| `…/availability` | yes | 1 | `online` / `offline`; set `offline` as MQTT last will |
| `…/inventory` | yes | 0 | optional, e.g. every 60 s: every CAN ID seen (not used by the integration) |

Home Assistant discovers a battery from its retained `info` message. Entities are created
for `module_count` modules with `cells_per_module` cells and `temps_per_module` sensors each.

## `info`

```json
{
  "schema": 1,
  "device_id": "elebox",
  "manufacturer": "EITAI",
  "model": "ELEBOX-HV",
  "module_count": 10,
  "cells_per_module": 16,
  "temps_per_module": 4,
  "module_versions": ["118109 128909 139101", "..."],
  "bridge_version": "0.1.0",
  "decoder_version": "0.1.0"
}
```

Required: `schema`, `module_count`. Optional: everything else (defaults 16 cells, 4 temperatures).

## `state`

```json
{
  "system": {
    "module_count": 10,
    "cell_count": 160,
    "soc_pct": 28,
    "pack_voltage_v": 529.46,
    "cell_min_mv": 3270, "cell_min_module": 6, "cell_min_cell": 7,
    "cell_max_mv": 3312, "cell_max_module": 1, "cell_max_cell": 16,
    "cell_avg_mv": 3309.2,
    "cell_delta_mv": 42,
    "cell_min_below_avg_mv": 39.2,
    "temp_min_c": 28, "temp_max_c": 33,
    "reference_cell_mv": 3309,
    "system_records_raw": {"07": "050003fdce1c", "...": "..."},
    "counter_08_raw": 76470,
    "counter_0a_raw": 369140
  },
  "modules": [
    {
      "module": 1,
      "cells_mv": [3310, 3307, "... 16 values, null if not received yet"],
      "temps_c": [32, 33, 32, 33],
      "voltage_v": 52.9,
      "cell_min_mv": 3307, "cell_min_index": 2,
      "cell_max_mv": 3312, "cell_max_index": 3,
      "cell_avg_mv": 3309.1,
      "cell_delta_mv": 5,
      "temp_max_c": 33,
      "deviation_from_pack_avg_mv": -0.1,
      "min_cell_below_pack_avg_mv": 2.2,
      "version": "118109 128909 139101",
      "status_raw": "0001000000000000",
      "balance_state_raw": "0000000000000000",
      "balance_cmd_raw": "0100000000000000",
      "balancing": false,
      "summary_byte2": 240
    }
  ],
  "frames_total": 7548,
  "timestamp": 1792332827.0
}
```

* `modules[].module` is 1-based and must match `info.module_count`.
* Every field is optional; a missing field makes the corresponding entity *unknown*.
  A minimal publisher only needs `modules[].module`, `modules[].cells_mv` and `modules[].temps_c`;
  the derived values (min/max/avg/deviation) can be computed by the publisher or left out.
* Units: voltages of cells in mV (integer), module/pack voltages in V, temperatures in °C.
* `soc_pct` is the state of charge the BMS reports (last byte of system record `07`).
* `balancing` is `true` when the module reports a non-zero balancing state (PF `0x41`). Only the all-zero
  state has been observed so far, so the meaning of individual bits is not known yet.
* Fields ending in `_raw` are undecoded bus data and may change meaning in later schema versions.

## Versioning

New optional fields may be added without changing `schema`. Removing or changing the meaning of a
field increments `schema`; the integration warns when it sees a newer schema than it supports.

## `inventory` (optional)

For reverse engineering. The integration ignores it; the Docker bridge publishes it every `INVENTORY_INTERVAL`
seconds (default 60). `known` is false for IDs not described in [can-protocol.md](can-protocol.md).
`payloads` lists distinct payloads with their counts while there are at most 8, otherwise it is `null`;
`variants` counts distinct payloads up to 32 (`variants_overflow` = more).

```json
{
  "schema": 1,
  "since": 1792332790.1,
  "ids": [
    {"id": "1841F585", "known": true, "count": 4510, "period_ms": 790, "last_data": "0000000000000000",
     "variants": 1, "variants_overflow": false, "payloads": {"0000000000000000": 4510}}
  ]
}
```

