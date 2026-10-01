"""Actions (reset alarms, sync the Nilan's clock)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NilanConfigEntry
from .entity import NilanEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NilanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities(NilanButton(hub, desc) for desc in hub.descriptions("button"))


class NilanButton(NilanEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.hub.async_command(self.key, "PRESS")
