"""Config flow: auto-discovered from the bridge's retained MQTT info topic, or added manually."""
from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import CONF_DEVICE_ID, DOMAIN, MODEL, TOPIC_ROOT


class EleboxConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._module_count: int | None = None

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        parts = discovery_info.topic.split("/")
        if len(parts) != 3 or parts[0] != TOPIC_ROOT or parts[2] != "info":
            return self.async_abort(reason="invalid_discovery_info")
        try:
            info = json.loads(discovery_info.payload)
        except ValueError:
            return self.async_abort(reason="invalid_discovery_info")
        self._device_id = parts[1]
        self._module_count = info.get("module_count")
        await self.async_set_unique_id(self._device_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": f"{MODEL} ({self._device_id})"}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._create()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"device_id": self._device_id, "modules": str(self._module_count or "?")},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE_ID].strip()
            await self.async_set_unique_id(self._device_id)
            self._abort_if_unique_id_configured()
            return self._create()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID, default="elebox"): str}),
        )

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(title=f"{MODEL} {self._device_id}", data={CONF_DEVICE_ID: self._device_id})
