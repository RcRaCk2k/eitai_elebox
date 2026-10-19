"""EITAI ELEBOX-HV battery, fed by the eitai-elebox CAN bridge over MQTT."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import CONF_DEVICE_ID, SIGNAL_AVAILABILITY, SIGNAL_INFO, SIGNAL_STATE, SUPPORTED_SCHEMA, TOPIC_ROOT

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


@dataclass
class EleboxData:
    device_id: str
    info: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    available: bool = False
    unsubscribe: list = field(default_factory=list)


type EleboxConfigEntry = ConfigEntry[EleboxData]


async def async_setup_entry(hass: HomeAssistant, entry: EleboxConfigEntry) -> bool:
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available")

    device_id = entry.data[CONF_DEVICE_ID]
    data = EleboxData(device_id)
    entry.runtime_data = data
    base = f"{TOPIC_ROOT}/{device_id}"

    @callback
    def on_info(msg: mqtt.ReceiveMessage) -> None:
        try:
            data.info = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("invalid info payload on %s", msg.topic)
            return
        if data.info.get("schema", 1) > SUPPORTED_SCHEMA:
            _LOGGER.warning("%s uses MQTT schema %s, this integration supports %s; please update",
                            msg.topic, data.info.get("schema"), SUPPORTED_SCHEMA)
        async_dispatcher_send(hass, SIGNAL_INFO.format(device_id))

    @callback
    def on_state(msg: mqtt.ReceiveMessage) -> None:
        try:
            data.state = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("invalid state payload on %s", msg.topic)
            return
        async_dispatcher_send(hass, SIGNAL_STATE.format(device_id))

    @callback
    def on_availability(msg: mqtt.ReceiveMessage) -> None:
        data.available = msg.payload == "online"
        async_dispatcher_send(hass, SIGNAL_AVAILABILITY.format(device_id))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # subscribe after the platforms are set up so retained messages reach their listeners
    for topic, cb in (("info", on_info), ("availability", on_availability), ("state", on_state)):
        data.unsubscribe.append(await mqtt.async_subscribe(hass, f"{base}/{topic}", cb, qos=1))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EleboxConfigEntry) -> bool:
    for unsub in entry.runtime_data.unsubscribe:
        unsub()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
