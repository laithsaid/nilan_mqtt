"""Read-only values: temperatures, percentages, states, texts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity, enum_or_none
from .hub import NilanHub


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanSensor(hub, desc) for desc in hub.descriptions("sensor"))


class NilanSensor(NilanEntity, SensorEntity):
    def __init__(self, hub: NilanHub, desc: dict[str, Any]) -> None:
        super().__init__(hub, desc)
        self._attr_native_unit_of_measurement = desc.get("unit_of_measurement")
        self._attr_device_class = enum_or_none(SensorDeviceClass, desc.get("device_class"))
        self._attr_state_class = enum_or_none(SensorStateClass, desc.get("state_class"))
        self._numeric = bool(
            self._attr_native_unit_of_measurement or self._attr_device_class or self._attr_state_class
        )

    @property
    def native_value(self) -> Any:
        reading = self.reading
        if self._numeric and (isinstance(reading, bool) or not isinstance(reading, (int, float))):
            return None       # Home Assistant refuses a text as the value of a sensor with a unit
        return reading
