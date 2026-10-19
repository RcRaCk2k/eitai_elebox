"""Sensors for the EITAI ELEBOX-HV system and its battery modules."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EleboxConfigEntry
from .entity import EleboxEntity, setup_platform

MV = UnitOfElectricPotential.MILLIVOLT
V = UnitOfElectricPotential.VOLT
C = UnitOfTemperature.CELSIUS


@dataclass(frozen=True, kw_only=True)
class EleboxSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


def _voltage(key: str, unit: str, field: str, precision: int = 0, **kw) -> EleboxSensorDescription:
    return EleboxSensorDescription(
        key=key, translation_key=key, device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=unit,
        suggested_display_precision=precision, value_fn=lambda d, f=field: d.get(f), **kw)


def _temp(key: str, field: str, **kw) -> EleboxSensorDescription:
    return EleboxSensorDescription(
        key=key, translation_key=key, device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=C,
        value_fn=lambda d, f=field: d.get(f), **kw)


def _location(prefix: str) -> Callable[[dict[str, Any]], str | None]:
    def fn(d: dict[str, Any]) -> str | None:
        m, c = d.get(f"{prefix}_module"), d.get(f"{prefix}_cell")
        return f"M{m} C{c}" if m and c else None
    return fn


def _raw(key: str, field: str) -> EleboxSensorDescription:
    return EleboxSensorDescription(
        key=key, translation_key=key, entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False, value_fn=lambda d, f=field: d.get(f))


SYSTEM_SENSORS: tuple[EleboxSensorDescription, ...] = (
    EleboxSensorDescription(key="soc", translation_key="soc", device_class=SensorDeviceClass.BATTERY,
                            state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
                            value_fn=lambda d: d.get("soc_pct")),
    _voltage("pack_voltage", V, "pack_voltage_v", 1),
    _voltage("cell_min", MV, "cell_min_mv"),
    _voltage("cell_max", MV, "cell_max_mv"),
    _voltage("cell_avg", MV, "cell_avg_mv", 1),
    _voltage("cell_delta", MV, "cell_delta_mv"),
    _voltage("cell_min_below_avg", MV, "cell_min_below_avg_mv", 1),
    EleboxSensorDescription(key="cell_min_location", translation_key="cell_min_location",
                            value_fn=_location("cell_min")),
    EleboxSensorDescription(key="cell_max_location", translation_key="cell_max_location",
                            value_fn=_location("cell_max")),
    _temp("temp_min", "temp_min_c"),
    _temp("temp_max", "temp_max_c"),
    _voltage("reference_cell", MV, "reference_cell_mv", entity_category=EntityCategory.DIAGNOSTIC),
    EleboxSensorDescription(key="module_count", translation_key="module_count",
                            entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d.get("module_count")),
    *(
        EleboxSensorDescription(
            key=f"system_record_{rec}", translation_key="system_record", translation_placeholders={"record": rec},
            entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
            value_fn=lambda d, r=rec: d.get("system_records_raw", {}).get(r))
        for rec in ("07", "08", "09", "0a", "0b", "0c")
    ),
    *(
        EleboxSensorDescription(
            key=f"counter_{rec}", translation_key="counter", translation_placeholders={"record": rec},
            entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
            value_fn=lambda d, r=rec: d.get(f"counter_{r}_raw"))
        for rec in ("08", "0a")
    ),
)

MODULE_SENSORS: tuple[EleboxSensorDescription, ...] = (
    _voltage("module_voltage", V, "voltage_v", 1),
    _voltage("cell_min", MV, "cell_min_mv"),
    _voltage("cell_max", MV, "cell_max_mv"),
    _voltage("cell_avg", MV, "cell_avg_mv", 1),
    _voltage("cell_delta", MV, "cell_delta_mv"),
    _voltage("deviation_from_pack_avg", MV, "deviation_from_pack_avg_mv", 1),
    _voltage("min_cell_below_pack_avg", MV, "min_cell_below_pack_avg_mv", 1),
    EleboxSensorDescription(key="cell_min_index", translation_key="cell_min_index",
                            value_fn=lambda d: d.get("cell_min_index")),
    _temp("temp_max", "temp_max_c"),
    _raw("status_raw", "status_raw"),
    _raw("balance_state_raw", "balance_state_raw"),
    _raw("balance_cmd_raw", "balance_cmd_raw"),
    _raw("summary_byte2", "summary_byte2"),
    EleboxSensorDescription(key="firmware", translation_key="firmware", entity_category=EntityCategory.DIAGNOSTIC,
                            value_fn=lambda d: d.get("version")),
)


def _cell_sensors(count: int) -> list[EleboxSensorDescription]:
    return [
        EleboxSensorDescription(
            key=f"cell_{i + 1}", translation_key="cell_voltage", translation_placeholders={"cell": str(i + 1)},
            device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=MV, suggested_display_precision=0,
            value_fn=lambda d, i=i: (d.get("cells_mv") or [None] * count)[i])
        for i in range(count)
    ]


def _temp_sensors(count: int) -> list[EleboxSensorDescription]:
    return [
        EleboxSensorDescription(
            key=f"temp_{i + 1}", translation_key="temp_sensor", translation_placeholders={"sensor": str(i + 1)},
            device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=C, value_fn=lambda d, i=i: (d.get("temps_c") or [None] * count)[i])
        for i in range(count)
    ]


async def async_setup_entry(hass: HomeAssistant, entry: EleboxConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = entry.runtime_data

    def build(info: dict[str, Any], module: int | None, system_device_id: str) -> list[EleboxSensor]:
        if module is None:
            descriptions = SYSTEM_SENSORS
        else:
            descriptions = (*MODULE_SENSORS, *_cell_sensors(info.get("cells_per_module", 16)),
                            *_temp_sensors(info.get("temps_per_module", 4)))
        return [EleboxSensor(data, info, d, module, system_device_id) for d in descriptions]

    setup_platform(hass, entry, async_add_entities, build)


class EleboxSensor(EleboxEntity, SensorEntity):
    entity_description: EleboxSensorDescription

    @property
    def native_value(self) -> Any:
        return self._value()
