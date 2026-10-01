"""Take over the entities the reader announced through MQTT discovery.

Before this integration the reader announced its entities itself and Home Assistant's MQTT integration owned them.
Taking over keeps every entity id (history and statistics are stored per entity id, dashboards and automations refer
to it) and the user's settings (name, icon, area, labels, display precision, hidden / disabled, voice exposure):

  1. remember what the MQTT entities look like (kept in the config entry, so an interrupted take-over can go on);
  2. ask the reader to switch its discovery off -> the MQTT integration removes its entities;
  3. this integration creates its entities with the remembered ids;
  4. the remembered settings are put back.

Going back: remove this integration and switch "Home Assistant discovery" on again on the reader's page.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_SNAPSHOT, CONF_TAKEOVER_DONE, DOMAIN

_LOGGER = logging.getLogger(__name__)

READER_WAIT_S = 30        # for the reader to remove its discovery messages
FALLBACK_WAIT_S = 15      # after removing them ourselves (older reader, or reader not running)


@callback
def mqtt_entries(hass: HomeAssistant, node: str) -> list[er.RegistryEntry]:
    """The reader's entities owned by the MQTT integration (unique_id = <node>_<key>)."""
    registry = er.async_get(hass)
    prefix = f"{node}_"
    return [e for e in registry.entities.values() if e.platform == "mqtt" and e.unique_id.startswith(prefix)]


def _plain(value: Any) -> Any:
    """Registry values as JSON-friendly ones."""
    if isinstance(value, (set, frozenset, tuple, list)):
        return sorted(str(v) for v in value)
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _plain(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return getattr(value, "value", str(value))      # enums (hidden_by, disabled_by)


@callback
def _snapshot(hass: HomeAssistant, node: str, entries: list[er.RegistryEntry]) -> dict[str, Any]:
    entities = {}
    for e in entries:
        entities[e.unique_id[len(node) + 1:]] = {
            "entity_id": e.entity_id,
            "name": e.name,
            "icon": e.icon,
            "area_id": e.area_id,
            "labels": _plain(e.labels),
            "aliases": _plain(e.aliases),
            "hidden_by": _plain(e.hidden_by),
            "disabled_by": _plain(e.disabled_by),
            "options": _plain(e.options),
        }
    device = dr.async_get(hass).async_get_device(identifiers={("mqtt", node)})
    return {
        "entities": entities,
        "device": {
            "area_id": device.area_id,
            "name_by_user": device.name_by_user,
            "labels": _plain(device.labels),
        } if device else {},
    }


async def _wait_until_gone(hass: HomeAssistant, node: str, seconds: float) -> bool:
    for _ in range(int(seconds * 2)):
        if not mqtt_entries(hass, node):
            return True
        await asyncio.sleep(0.5)
    return not mqtt_entries(hass, node)


async def async_prepare(hass: HomeAssistant, entry: ConfigEntry, hub) -> None:
    """Steps 1 and 2. Called before this integration's entities are created."""
    node = hub.node
    entries = mqtt_entries(hass, node)
    if entry.data.get(CONF_SNAPSHOT) is None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_SNAPSHOT: _snapshot(hass, node, entries)}
        )
        _LOGGER.info("Taking over %d MQTT entities of %s", len(entries), hub.topic)
    if not entries:
        return
    await hub.async_command("ha_discovery", "OFF")
    if await _wait_until_gone(hass, node, READER_WAIT_S):
        return
    # The reader did not do it (older than 1.2.0, or not running): remove its discovery messages ourselves.
    _LOGGER.warning("%s did not switch its discovery off; removing its discovery messages", hub.topic)
    prefix = (hub.meta or {}).get("discovery_prefix") or "homeassistant"
    for e in mqtt_entries(hass, node):
        key = e.unique_id[len(node) + 1:]
        await mqtt.async_publish(hass, f"{prefix}/{e.domain}/{node}/{key}/config", "", qos=1, retain=True)
    if not await _wait_until_gone(hass, node, FALLBACK_WAIT_S):
        raise ConfigEntryNotReady(
            f"{len(mqtt_entries(hass, node))} MQTT entities of {hub.topic} are still there; switch 'Home Assistant "
            "discovery' off on the reader's page"
        )


@callback
def async_restore(hass: HomeAssistant, entry: ConfigEntry, hub) -> None:
    """Step 4. Called once, after this integration's entities exist."""
    snapshot = entry.data.get(CONF_SNAPSHOT) or {}
    registry = er.async_get(hass)
    restored = 0
    for key, old in (snapshot.get("entities") or {}).items():
        domain = old["entity_id"].split(".", 1)[0]
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{hub.node}_{key}")
        if entity_id is None:
            _LOGGER.warning("Take-over: %s is not offered by the reader any more", old["entity_id"])
            continue
        changes: dict[str, Any] = {}
        if entity_id != old["entity_id"]:
            if registry.async_get(old["entity_id"]) is None and hass.states.get(old["entity_id"]) is None:
                changes["new_entity_id"] = old["entity_id"]
            else:
                _LOGGER.warning("Take-over: %s is in use, the entity is now %s", old["entity_id"], entity_id)
        for field in ("name", "icon", "area_id"):
            if old.get(field) is not None:
                changes[field] = old[field]
        if old.get("labels"):
            changes["labels"] = set(old["labels"])
        if old.get("aliases"):
            changes["aliases"] = set(old["aliases"])
        if old.get("hidden_by"):
            changes["hidden_by"] = er.RegistryEntryHider(old["hidden_by"])
        if old.get("disabled_by"):
            changes["disabled_by"] = er.RegistryEntryDisabler(old["disabled_by"])
        try:
            if changes:
                entity_id = registry.async_update_entity(entity_id, **changes).entity_id
            for options_domain, options in (old.get("options") or {}).items():
                if isinstance(options, dict) and options:
                    registry.async_update_entity_options(entity_id, options_domain, options)
        except (ValueError, KeyError) as err:
            _LOGGER.warning("Take-over: settings of %s not restored: %s", old["entity_id"], err)
            continue
        restored += 1
    old_device = snapshot.get("device") or {}
    devices = dr.async_get(hass)
    device = devices.async_get_device(identifiers={(DOMAIN, hub.node)})
    if device and old_device:
        changes = {k: old_device[k] for k in ("area_id", "name_by_user") if old_device.get(k)}
        if old_device.get("labels"):
            changes["labels"] = set(old_device["labels"])
        if changes:
            devices.async_update_device(device.id, **changes)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TAKEOVER_DONE: True})
    _LOGGER.info("Take-over done: %d entities of %s keep their ids and settings", restored, hub.topic)
