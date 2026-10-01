"""Download for bug reports: what the reader describes and sends, and whether it is alive."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import NilanConfigEntry
from .const import CONF_SNAPSHOT


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: NilanConfigEntry) -> dict[str, Any]:
    hub = entry.runtime_data
    return {
        "entry": {
            "data": {k: v for k, v in entry.data.items() if k != CONF_SNAPSHOT},
            "options": dict(entry.options),
            "taken_over_entities": len((entry.data.get(CONF_SNAPSHOT) or {}).get("entities") or {}),
        },
        "reader": {"lwt": hub.lwt, "status": hub.status, "available": hub.available},
        "meta": hub.meta,
        "values": hub.values,
    }
