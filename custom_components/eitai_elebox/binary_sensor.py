"""Binary sensors for the EITAI ELEBOX-HV battery modules."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EleboxConfigEntry
from .entity import EleboxEntity, setup_platform


@dataclass(frozen=True, kw_only=True)
class EleboxBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


MODULE_BINARY_SENSORS: tuple[EleboxBinarySensorDescription, ...] = (
    EleboxBinarySensorDescription(key="balancing", translation_key="balancing",
                                  entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d.get("balancing")),
)


async def async_setup_entry(hass: HomeAssistant, entry: EleboxConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = entry.runtime_data

    def build(info: dict[str, Any], module: int | None, system_device_id: str) -> list[EleboxBinarySensor]:
        if module is None:
            return []
        return [EleboxBinarySensor(data, info, d, module, system_device_id) for d in MODULE_BINARY_SENSORS]

    setup_platform(hass, entry, async_add_entities, build)


class EleboxBinarySensor(EleboxEntity, BinarySensorEntity):
    entity_description: EleboxBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        return self._value()
