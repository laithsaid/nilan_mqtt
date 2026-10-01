"""Constants of the Nilan CTS 602 (MQTT) integration."""

from homeassistant.const import Platform

DOMAIN = "nilan_mqtt"

CONF_TOPIC = "topic"
CONF_TAKEOVER = "takeover"                # take over the entities the reader announced through MQTT discovery
CONF_TAKEOVER_DONE = "takeover_done"
CONF_SNAPSHOT = "takeover_snapshot"       # what those entities looked like (ids, names, areas, settings)
CONF_SILENCE_MIN = "silence_minutes"

DEFAULT_TOPIC = "nilan/CTS602"
DEFAULT_SILENCE_MIN = 10

# Highest <topic>/meta "protocol" this version understands (see ha.py of the reader)
PROTOCOL = 1

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CARD_FILE = "nilan-unit-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
