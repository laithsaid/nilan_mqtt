"""Writable on/off values (run, week schedule)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanSwitch(hub, desc) for desc in hub.descriptions("switch"))


class NilanSwitch(NilanEntity, SwitchEntity):
    """The state only changes when the reader has read the new value back from the unit."""

    @property
    def is_on(self) -> bool | None:
        reading = self.reading
        return None if reading is None else reading == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_command(self.key, "ON")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_command(self.key, "OFF")
