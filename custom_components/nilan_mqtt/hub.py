"""The connection to one nilan-mqtt reader: its MQTT topics, the last values and whether it is alive.

Topics of the reader (see its poller.py / ha.py):
  <topic>/meta     description of the entities (retained)
  <topic>/state    one JSON with all values (retained)
  <topic>/status   "online" | "read error"  (does the Nilan answer the reader)
  <topic>/lwt      "online" | "offline"     (does the reader run)
  <topic>/set/<key>  commands
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .const import CONF_SILENCE_MIN, CONF_SNAPSHOT, CONF_TOPIC, DEFAULT_SILENCE_MIN, DOMAIN

_LOGGER = logging.getLogger(__name__)


def parse_meta(payload: str | bytes | None) -> dict[str, Any] | None:
    """The reader's <topic>/meta message as a dict, or None when it is not one."""
    if not payload:
        return None
    try:
        meta = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get("entities"), list):
        return None
    if not isinstance(meta.get("protocol"), int) or not meta.get("node") or not meta.get("topic"):
        return None
    return meta


def entities_signature(meta: dict[str, Any]) -> str:
    """Changes when an entity is added, removed or described differently (then the entry is reloaded)."""
    return json.dumps(sorted(meta["entities"], key=lambda e: e.get("key", "")), sort_keys=True)


class NilanHub:
    """Listens to one reader and hands its values to the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.topic: str = entry.data[CONF_TOPIC]
        self.meta: dict[str, Any] | None = None
        self.values: dict[str, Any] = {}
        self.lwt: str | None = None
        self.status: str | None = None
        self.meta_ready = asyncio.Event()
        self.signal = f"{DOMAIN}_{entry.entry_id}_update"
        self._unsubs: list[CALLBACK_TYPE] = []
        self._silence_timer: CALLBACK_TYPE | None = None
        self._signature: str | None = None

    # ---- what the entities ask ----
    @property
    def node(self) -> str:
        return self.meta["node"] if self.meta else ""

    @property
    def available(self) -> bool:
        return self.lwt == "online" and self.status == "online"

    @property
    def device_info(self) -> DeviceInfo:
        device = (self.meta or {}).get("device") or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.node)},
            name=device.get("name") or "Nilan",
            manufacturer=device.get("manufacturer") or "Nilan",
            model=device.get("model"),
            sw_version=device.get("sw_version"),
            hw_version=device.get("hw_version"),
        )

    def entity_id_for(self, desc: dict[str, Any]) -> str | None:
        """The entity id an entity should get: the one it had under MQTT discovery, else the reader's suggestion."""
        taken_over = ((self.entry.data.get(CONF_SNAPSHOT) or {}).get("entities") or {}).get(desc["key"]) or {}
        return taken_over.get("entity_id") or desc.get("entity_id")

    def descriptions(self, component: str) -> list[dict[str, Any]]:
        return [e for e in (self.meta or {}).get("entities", []) if e.get("component") == component and e.get("key")]

    async def async_command(self, key: str, payload: str) -> None:
        await mqtt.async_publish(self.hass, f"{self.topic}/set/{key}", payload, qos=1, retain=False)

    # ---- MQTT ----
    async def async_start(self) -> None:
        for suffix, handler in (
            ("meta", self._on_meta),
            ("state", self._on_state),
            ("status", self._on_status),
            ("lwt", self._on_lwt),
        ):
            self._unsubs.append(await mqtt.async_subscribe(self.hass, f"{self.topic}/{suffix}", handler, qos=1))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._silence_timer:
            self._silence_timer()
            self._silence_timer = None

    @callback
    def _on_meta(self, msg: mqtt.ReceiveMessage) -> None:
        meta = parse_meta(msg.payload)
        if meta is None:
            return
        signature = entities_signature(meta)
        first = self.meta is None
        changed = not first and signature != self._signature
        self.meta, self._signature = meta, signature
        if first:
            self.meta_ready.set()
            return
        if changed:
            _LOGGER.info("%s: the reader's entity list changed, reloading", self.topic)
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return
        self._update_device()

    @callback
    def _update_device(self) -> None:
        """Versions arrive after the reader's first read: keep the device page up to date without a reload."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.node)})
        info = (self.meta or {}).get("device") or {}
        if device and (device.sw_version != info.get("sw_version") or device.hw_version != info.get("hw_version")):
            registry.async_update_device(device.id, sw_version=info.get("sw_version"), hw_version=info.get("hw_version"))

    @callback
    def _on_state(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            values = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("%s/state is not JSON, ignored", self.topic)
            return
        if isinstance(values, dict):
            self.values = values
            async_dispatcher_send(self.hass, self.signal)

    @callback
    def _on_status(self, msg: mqtt.ReceiveMessage) -> None:
        self.status = str(msg.payload)
        self._availability_changed()

    @callback
    def _on_lwt(self, msg: mqtt.ReceiveMessage) -> None:
        self.lwt = str(msg.payload)
        self._availability_changed()

    # ---- "the reader is silent" warning (Settings -> Repairs) ----
    @callback
    def _availability_changed(self) -> None:
        async_dispatcher_send(self.hass, self.signal)
        self.watch_silence()

    @callback
    def watch_silence(self) -> None:
        if self.available:
            if self._silence_timer:
                self._silence_timer()
                self._silence_timer = None
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        elif self._silence_timer is None:
            minutes = self.entry.options.get(CONF_SILENCE_MIN, DEFAULT_SILENCE_MIN)
            self._silence_timer = async_call_later(self.hass, minutes * 60, self._silent_too_long)

    @property
    def _issue_id(self) -> str:
        return f"silent_{self.entry.entry_id}"

    @callback
    def _silent_too_long(self, _now: Any) -> None:
        self._silence_timer = None
        if self.available:
            return
        reader_down = self.lwt != "online"
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="reader_offline" if reader_down else "unit_silent",
            translation_placeholders={
                "name": self.entry.title,
                "topic": self.topic,
                "minutes": str(self.entry.options.get(CONF_SILENCE_MIN, DEFAULT_SILENCE_MIN)),
            },
        )
