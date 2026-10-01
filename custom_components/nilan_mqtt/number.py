"""Writable numbers (room setpoint, supply air limits, times, ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity, enum_or_none
from .hub import NilanHub


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanNumber(hub, desc) for desc in hub.descriptions("number"))


class NilanNumber(NilanEntity, NumberEntity):
    """The reader checks the limits again and reads the value back; the state follows that."""

    _attr_mode = NumberMode.BOX

    def __init__(self, hub: NilanHub, desc: dict[str, Any]) -> None:
        super().__init__(hub, desc)
        self._attr_native_unit_of_measurement = desc.get("unit_of_measurement")
        self._attr_device_class = enum_or_none(NumberDeviceClass, desc.get("device_class"))
        if isinstance(desc.get("min"), (int, float)):
            self._attr_native_min_value = desc["min"]
        if isinstance(desc.get("max"), (int, float)):
            self._attr_native_max_value = desc["max"]
        if isinstance(desc.get("step"), (int, float)) and desc["step"] > 0:
            self._attr_native_step = desc["step"]

    @property
    def native_value(self) -> float | None:
        reading = self.reading
        return reading if isinstance(reading, (int, float)) and not isinstance(reading, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_command(self.key, str(int(value)) if float(value).is_integer() else str(value))
