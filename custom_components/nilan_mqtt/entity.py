"""What all Nilan entities share."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .hub import NilanHub


def enum_or_none(enum_class: type, value: Any) -> Any:
    """'temperature' -> SensorDeviceClass.TEMPERATURE; unknown or missing -> None."""
    if not value:
        return None
    try:
        return enum_class(value)
    except ValueError:
        return None


class NilanEntity(Entity):
    """One entry of the reader's <topic>/meta list."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # The reader's descriptions are long and never change: show them, don't store them with every state.
    _unrecorded_attributes = frozenset({"description", "register", "allowed values"})

    def __init__(self, hub: NilanHub, desc: dict[str, Any]) -> None:
        self.hub = hub
        self.desc = desc
        self.key: str = desc["key"]
        self._attr_unique_id = f"{hub.node}_{self.key}"
        self._attr_name = desc.get("name") or self.key
        self._attr_icon = desc.get("icon")
        self._attr_entity_category = enum_or_none(EntityCategory, desc.get("entity_category"))
        self._attr_extra_state_attributes = dict(desc.get("attributes") or {})
        self._attr_device_info = hub.device_info
        entity_id = hub.entity_id_for(desc)
        if entity_id:
            self.entity_id = entity_id

    @property
    def available(self) -> bool:
        return self.hub.available

    @property
    def reading(self) -> Any:
        """The reader's last value for this entity (None = not sent)."""
        return self.hub.values.get(self.key)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.hub.signal, self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()
