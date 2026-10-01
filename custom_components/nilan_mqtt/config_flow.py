"""Set-up form: found by itself through <topic>/meta, or added by hand with the topic."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import (
    CONF_SILENCE_MIN,
    CONF_TAKEOVER,
    CONF_TOPIC,
    DEFAULT_SILENCE_MIN,
    DEFAULT_TOPIC,
    DOMAIN,
    PROTOCOL,
)
from .hub import parse_meta
from .takeover import mqtt_entries

META_WAIT_S = 5


async def _fetch_meta(hass: HomeAssistant, topic: str) -> dict[str, Any] | None:
    """The retained <topic>/meta message, or None when nothing (usable) is there."""
    received: asyncio.Future[str] = hass.loop.create_future()

    @callback
    def got(msg: mqtt.ReceiveMessage) -> None:
        if not received.done() and msg.payload:
            received.set_result(msg.payload)

    unsubscribe = await mqtt.async_subscribe(hass, f"{topic}/meta", got, qos=1)
    try:
        async with asyncio.timeout(META_WAIT_S):
            payload = await received
    except TimeoutError:
        return None
    finally:
        unsubscribe()
    return parse_meta(payload)


class NilanConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._topic: str = DEFAULT_TOPIC
        self._meta: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NilanOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            topic = user_input[CONF_TOPIC].strip().strip("/")
            if not await mqtt.async_wait_for_mqtt_client(self.hass):
                errors["base"] = "mqtt_unavailable"
            elif (meta := await _fetch_meta(self.hass, topic)) is None:
                errors["base"] = "no_meta"
            elif meta["protocol"] > PROTOCOL:
                errors["base"] = "newer_protocol"
            else:
                await self.async_set_unique_id(meta["node"])
                self._abort_if_unique_id_configured()
                self._topic, self._meta = topic, meta
                return await self.async_step_confirm()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TOPIC, default=self._topic): str}),
            errors=errors,
        )

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """The reader's <topic>/meta message was seen on the broker."""
        meta = parse_meta(discovery_info.payload)
        if meta is None or not discovery_info.topic.endswith("/meta"):
            return self.async_abort(reason="invalid_discovery_info")
        if meta["protocol"] > PROTOCOL:
            return self.async_abort(reason="newer_protocol")
        await self.async_set_unique_id(meta["node"])
        self._abort_if_unique_id_configured()
        self._topic, self._meta = discovery_info.topic[: -len("/meta")], meta
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    @property
    def _name(self) -> str:
        return (self._meta.get("device") or {}).get("name") or "Nilan"

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        found = len(mqtt_entries(self.hass, self._meta["node"]))
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_TOPIC: self._topic, CONF_TAKEOVER: bool(user_input.get(CONF_TAKEOVER, False))},
            )
        schema = vol.Schema({vol.Required(CONF_TAKEOVER, default=True): bool}) if found else vol.Schema({})
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={
                "name": self._name,
                "topic": self._topic,
                "version": str(self._meta.get("version") or "?"),
                "entities": str(len(self._meta["entities"])),
                "found": str(found),
            },
        )


class NilanOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SILENCE_MIN, DEFAULT_SILENCE_MIN)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SILENCE_MIN, default=current): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))}
            ),
        )
