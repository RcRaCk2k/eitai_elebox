"""Binary sensors for the EITAI ELEBOX-HV battery modules."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EleboxConfigEntry
from .entity import EleboxEntity, setup_platform


@dataclass(frozen=True, kw_only=True)
class EleboxBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


MODULE_BINARY_SENSORS: tuple[EleboxBinarySensorDescription, ...] = (
    EleboxBinarySensorDescription(key="balancing", translation_key="balancing",
                                  entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d.get("balancing"),
                                  attrs_fn=lambda d: {"cells": d.get("balancing_cells")}),
    EleboxBinarySensorDescription(key="fault", translation_key="fault", device_class=BinarySensorDeviceClass.PROBLEM,
                                  entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d.get("fault"),
                                  attrs_fn=lambda d: {"faults": d.get("faults")}),
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

    def _snapshot(self) -> tuple:
        # also write when only the attributes change, e.g. a different cell starts balancing
        return (*super()._snapshot(), str(self.extra_state_attributes))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        src = self._source()
        fn = self.entity_description.attrs_fn
        return fn(src) if fn and src is not None else None
