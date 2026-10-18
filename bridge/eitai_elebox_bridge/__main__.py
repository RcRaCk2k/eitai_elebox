"""EITAI ELEBOX-HV CAN -> MQTT bridge.

Topics (prefix eitai_elebox/<device_id>):
Payload format: docs/mqtt-format.md (any publisher, e.g. an ESP32, can implement it).

  /info          retained JSON: model, module/cell counts, versions. Triggers HA discovery.
  /state         JSON snapshot every INTERVAL seconds (see eitai_elebox.BatteryState.as_dict)
  /availability  "online" / "offline" (retained, also last will)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time

import paho.mqtt.client as mqtt

from eitai_elebox import BatteryState, __version__ as LIB_VERSION
from .sources import ReplaySource, SocketCanSource, ZlgSource

BRIDGE_VERSION = "0.1.0"
TOPIC_ROOT = "eitai_elebox"
SCHEMA_VERSION = 1  # see docs/mqtt-format.md
STALE_AFTER = 30

_LOG = logging.getLogger("eitai_elebox_bridge")


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"missing environment variable {name}")
    return val


def make_source():
    kind = env("SOURCE", "socketcan")
    if kind == "zlg":
        return ZlgSource(env("ZLG_LIB", "/opt/zlg/libusbcan.so"), int(env("ZLG_DEVICE_INDEX", "0")),
                         int(env("ZLG_CHANNEL", "0")))
    if kind == "socketcan":
        return SocketCanSource(env("CAN_IFACE", "can0"))
    if kind == "replay":
        return ReplaySource(env("REPLAY_FILE"))
    sys.exit(f"unknown SOURCE {kind!r} (use zlg, socketcan or replay)")


def main() -> None:
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    device_id = env("DEVICE_ID", "elebox")
    interval = float(env("INTERVAL", "5"))
    base = f"{TOPIC_ROOT}/{device_id}"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"eitai-elebox-bridge-{device_id}")
    if user := os.environ.get("MQTT_USER"):
        client.username_pw_set(user, os.environ.get("MQTT_PASSWORD"))
    client.will_set(f"{base}/availability", "offline", qos=1, retain=True)
    client.connect(env("MQTT_HOST", "localhost"), int(env("MQTT_PORT", "1883")))
    client.loop_start()

    def shutdown(*_):
        client.publish(f"{base}/availability", "offline", qos=1, retain=True).wait_for_publish(5)
        client.loop_stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    state = BatteryState()
    started = time.time()
    next_publish = started + interval
    online = None
    published_info = None

    for frame in make_source().frames():
        if frame is not None:
            state.update(frame)
        now = time.time()
        if now < next_publish:
            continue
        next_publish = now + interval

        is_online = now - state.last_frame < STALE_AFTER if state.last_frame else False
        if is_online != online:
            online = is_online
            client.publish(f"{base}/availability", "online" if online else "offline", qos=1, retain=True)
            _LOG.info("battery %s", "online" if online else "offline")
        if not online:
            continue

        snap = state.as_dict()
        # wait 10 s after start so all modules have reported before announcing the topology
        if now - started > 10:
            info = {
                "schema": SCHEMA_VERSION,
                "device_id": device_id,
                "model": "ELEBOX-HV",
                "manufacturer": "EITAI",
                "module_count": snap["system"]["module_count"],
                "cells_per_module": 16,
                "temps_per_module": 4,
                "module_versions": [m["version"] for m in snap["modules"]],
                "bridge_version": BRIDGE_VERSION,
                "decoder_version": LIB_VERSION,
            }
            if info != published_info:
                client.publish(f"{base}/info", json.dumps(info), qos=1, retain=True)
                published_info = info
                _LOG.info("announced %d modules", info["module_count"])
        client.publish(f"{base}/state", json.dumps(snap, separators=(",", ":")), qos=0, retain=True)


if __name__ == "__main__":
    main()
