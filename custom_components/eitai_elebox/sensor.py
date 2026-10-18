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
from homeassistant.const import EntityCategory, UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EleboxConfigEntry, EleboxData
from .const import DOMAIN, MANUFACTURER, MODEL, SIGNAL_AVAILABILITY, SIGNAL_INFO, SIGNAL_STATE

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
    _voltage("pack_voltage", V, "pack_voltage_v", 1),
    _voltage("cell_min", MV, "cell_min_mv"),
    _voltage("cell_max", MV, "cell_max_mv"),
    _voltage("cell_avg", MV, "cell_avg_mv", 1),
    _voltage("cell_delta", MV, "cell_delta_mv"),
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
    added_modules: set[int] = set()
    system_added = False

    @callback
    def on_info() -> None:
        nonlocal system_added
        info = data.info or {}
        # register the system device first so modules can reference it by registry id
        system_device = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id, **_system_device_info(data.device_id, info))
        new: list[EleboxSensor] = []
        if not system_added:
            new += [EleboxSensor(data, info, d, None, system_device.id) for d in SYSTEM_SENSORS]
            system_added = True
        cells = info.get("cells_per_module", 16)
        temps = info.get("temps_per_module", 4)
        for mod in range(1, info.get("module_count", 0) + 1):
            if mod in added_modules:
                continue
            added_modules.add(mod)
            for d in (*MODULE_SENSORS, *_cell_sensors(cells), *_temp_sensors(temps)):
                new.append(EleboxSensor(data, info, d, mod, system_device.id))
        if new:
            async_add_entities(new)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_INFO.format(data.device_id), on_info))
    if data.info:
        on_info()


def _system_device_info(device_id: str, info: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, device_id)}, manufacturer=MANUFACTURER, model=MODEL,
                      name=f"{MODEL} {device_id}", sw_version=info.get("bridge_version"))


class EleboxSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: EleboxSensorDescription

    def __init__(self, data: EleboxData, info: dict[str, Any], description: EleboxSensorDescription,
                 module: int | None, system_device_id: str) -> None:
        self.entity_description = description
        self._data = data
        self._module = module
        dev = data.device_id
        if module is None:
            self._attr_unique_id = f"{dev}_{description.key}"
            self._attr_device_info = _system_device_info(dev, info)
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

    @property
    def available(self) -> bool:
        return self._data.available and self._source() is not None

    @property
    def native_value(self) -> Any:
        src = self._source()
        return self.entity_description.value_fn(src) if src is not None else None

    @callback
    def _handle_update(self) -> None:
        # ~230 entities get a snapshot every few seconds: only write real changes to keep the recorder small
        current = (self.available, self.native_value)
        if current != self._last_written:
            self._last_written = current
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._last_written: tuple[bool, Any] | None = None
        for signal in (SIGNAL_STATE, SIGNAL_AVAILABILITY):
            self.async_on_remove(async_dispatcher_connect(
                self.hass, signal.format(self._data.device_id), self._handle_update))
        self._handle_update()
