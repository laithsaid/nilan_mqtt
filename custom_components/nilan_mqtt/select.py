"""Writable choices (operating mode, ventilation step, week program, ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity
from .hub import NilanHub


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanSelect(hub, desc) for desc in hub.descriptions("select"))


class NilanSelect(NilanEntity, SelectEntity):
    def __init__(self, hub: NilanHub, desc: dict[str, Any]) -> None:
        super().__init__(hub, desc)
        self._attr_options = [str(option) for option in desc.get("options") or []]

    @property
    def current_option(self) -> str | None:
        reading = self.reading
        return str(reading) if reading is not None and str(reading) in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_command(self.key, option)
