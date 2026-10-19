"""Base entity shared by the EITAI ELEBOX-HV platforms."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription

from . import EleboxConfigEntry, EleboxData
from .const import DOMAIN, MANUFACTURER, MODEL, SIGNAL_AVAILABILITY, SIGNAL_INFO, SIGNAL_STATE


def system_device_info(device_id: str, info: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, device_id)}, manufacturer=MANUFACTURER, model=MODEL,
                      name=f"{MODEL} {device_id}", sw_version=info.get("bridge_version"))


def setup_platform(
    hass: HomeAssistant,
    entry: EleboxConfigEntry,
    add_entities: Callable[[list[Entity]], None],
    build: Callable[[dict[str, Any], int | None, str], list[Entity]],
) -> None:
    """Create entities once `info` is known; build(info, module or None for the system, system device id)."""
    data = entry.runtime_data
    added_modules: set[int] = set()
    system_added = False

    @callback
    def on_info() -> None:
        nonlocal system_added
        info = data.info or {}
        # register the system device first so modules can reference it by registry id
        system_device = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id, **system_device_info(data.device_id, info))
        new: list[Entity] = []
        if not system_added:
            new += build(info, None, system_device.id)
            system_added = True
        for mod in range(1, info.get("module_count", 0) + 1):
            if mod not in added_modules:
                added_modules.add(mod)
                new += build(info, mod, system_device.id)
        if new:
            add_entities(new)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_INFO.format(data.device_id), on_info))
    if data.info:
        on_info()


class EleboxEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: EleboxData, info: dict[str, Any], description: EntityDescription,
                 module: int | None, system_device_id: str) -> None:
        self.entity_description = description
        self._data = data
        self._module = module
        dev = data.device_id
        if module is None:
            self._attr_unique_id = f"{dev}_{description.key}"
            self._attr_device_info = system_device_info(dev, info)
        else:
            versions = info.get("module_versions") or []
            self._attr_unique_id = f"{dev}_m{module}_{description.key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{dev}_m{module}")}, manufacturer=MANUFACTURER, model=f"{MODEL} module",
                name=f"{MODEL} {dev} Module {module}", via_device_id=system_device_id,
                sw_version=versions[module - 1] if module <= len(versions) else None)

    def _source(self) -> dict[str, Any] | None:
        state = self._data.state
        if not state:
            return None
        if self._module is None:
            return state.get("system")
        for m in state.get("modules", []):
            if m.get("module") == self._module:
                return m
        return None

    def _value(self) -> Any:
        src = self._source()
        return self.entity_description.value_fn(src) if src is not None else None

    @property
    def available(self) -> bool:
        return self._data.available and self._source() is not None

    @callback
    def _handle_update(self) -> None:
        # ~230 entities get a snapshot every few seconds: only write real changes to keep the recorder small
        current = (self.available, self._value())
        if current != self._last_written:
            self._last_written = current
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._last_written: tuple[bool, Any] | None = None
        for signal in (SIGNAL_STATE, SIGNAL_AVAILABILITY):
            self.async_on_remove(async_dispatcher_connect(
                self.hass, signal.format(self._data.device_id), self._handle_update))
        self._handle_update()
