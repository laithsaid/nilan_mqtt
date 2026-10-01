"""Nilan CTS 602 (MQTT): the Nilan ventilation unit as a Home Assistant device.

The values come from the nilan-mqtt reader (this repository's nilan-mqtt.py, running next to the unit's RS485 adapter)
over MQTT; this integration creates the entities, sends the commands and ships the dashboard card.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import takeover
from .const import (
    CARD_FILE,
    CARD_URL,
    CONF_TAKEOVER,
    CONF_TAKEOVER_DONE,
    DOMAIN,
    PLATFORMS,
    PROTOCOL,
)
from .hub import NilanHub

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
META_WAIT_S = 15

NilanConfigEntry = ConfigEntry[NilanHub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card and make the dashboards load it."""
    card = Path(__file__).parent / "www" / CARD_FILE
    if not await hass.async_add_executor_job(card.is_file):
        return True
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])
    version = (await async_get_integration(hass, DOMAIN)).version
    await _async_register_card(hass, f"{CARD_URL}?v={version}")
    return True


async def _async_register_card(hass: HomeAssistant, url: str) -> None:
    """Add the card to the dashboard resources (Settings -> Dashboards -> Resources), or update its version there.

    A resource is loaded by every browser and the app the next time a dashboard opens. `add_extra_js_url` alone is not
    enough: it only reaches a browser after its cached start page is refreshed, and until then the card is missing.
    It is the fallback for dashboards kept in YAML, which have no resource list to add to.
    """
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        add_extra_js_url(hass, url)
        return
    try:
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == CARD_URL:
                if item["url"] != url:
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                return
        await resources.async_create_item({"res_type": "module", "url": url})
    except Exception:  # noqa: BLE001 - the card must not keep the integration from loading
        _LOGGER.exception("Could not add %s to the dashboard resources; loading it as an extra module", url)
        add_extra_js_url(hass, url)


async def async_setup_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> bool:
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("Home Assistant's MQTT integration is not connected")
    hub = NilanHub(hass, entry)
    await hub.async_start()
    try:
        async with asyncio.timeout(META_WAIT_S):
            await hub.meta_ready.wait()
    except TimeoutError as err:
        await hub.async_stop()
        raise ConfigEntryNotReady(
            f"Nothing on {hub.topic}/meta: is the nilan-mqtt reader (1.2.0 or newer) running?"
        ) from err
    if hub.meta["protocol"] > PROTOCOL:
        await hub.async_stop()
        raise ConfigEntryError(
            f"The reader speaks protocol {hub.meta['protocol']}, this integration knows {PROTOCOL}: update the integration"
        )
    entry.runtime_data = hub

    taking_over = entry.data.get(CONF_TAKEOVER) and not entry.data.get(CONF_TAKEOVER_DONE)
    try:
        if taking_over:
            await takeover.async_prepare(hass, entry, hub)
        dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **hub.device_info)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hub.async_stop()
        raise
    if taking_over:
        takeover.async_restore(hass, entry, hub)
    hub.watch_silence()
    entry.async_on_unload(entry.add_update_listener(_async_options_changed))
    return True


async def _async_options_changed(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
