"""Read-only on/off values (running, summer mode, defrosting, ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity, enum_or_none
from .hub import NilanHub


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanBinarySensor(hub, desc) for desc in hub.descriptions("binary_sensor"))


class NilanBinarySensor(NilanEntity, BinarySensorEntity):
    def __init__(self, hub: NilanHub, desc: dict[str, Any]) -> None:
        super().__init__(hub, desc)
        self._attr_device_class = enum_or_none(BinarySensorDeviceClass, desc.get("device_class"))

    @property
    def is_on(self) -> bool | None:
        reading = self.reading
        return None if reading is None else reading == "ON"
