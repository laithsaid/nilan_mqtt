"""
Home Assistant MQTT discovery for the register table.

access read  -> sensor (number, enum, text, clock) / binary_sensor (bool)
access write -> number / select / switch / button
Entity ids: <component>.nilan_<key>. All values come from one JSON state topic (<topic>/state).
An entity is available while the program runs (<topic>/lwt) and the unit answers (<topic>/status).
Every entity gets attributes (description, register, range) from <topic>/attributes/<key>.

Extra entities that are not registers: switch.nilan_schedule (the page's week schedule on/off),
sensor.nilan_schedule_next, button.nilan_sync_clock, sensor.nilan_clock_drift.
"""

import json
import re

import registers as regs_mod

EXTRAS = [
  dict(key="schedule", name="Week schedule", kind="bool", access="write", icon="mdi:calendar-clock",
       desc="Turns the week schedule on the Nilan page on or off. The schedule sets the ventilation step and/or the "
            "room setpoint when each period starts; the periods are edited on the page."),
  dict(key="schedule_next", name="Week schedule next change", kind="text", access="read", icon="mdi:calendar-arrow-right",
       desc="The next period of the week schedule: weekday, time and what it sets ('none' without periods)."),
  dict(key="sync_clock", name="Sync Nilan clock", kind="button", access="write", icon="mdi:clock-check-outline",
       category="config",
       desc="Sets the Nilan controller's clock to the Raspberry Pi's time (the Nilan week programs and alarm log use it)."),
  dict(key="clock_drift", name="Nilan clock drift", kind="number", access="read", unit="s", device_class="duration",
       state_class="measurement", icon="mdi:clock-alert-outline", category="diagnostic",
       desc="Nilan clock minus the Pi's clock in seconds (negative = the Nilan is behind)."),
]


def node_id(topic):
  """nilan/CTS602 -> nilan_cts602 (discovery node and unique_id prefix)"""
  return re.sub(r"[^a-z0-9_]", "_", topic.lower())


def component(r):
  if r["access"] == "write":
    return {"number": "number", "enum": "select", "bool": "switch", "button": "button"}.get(r["kind"], "sensor")
  if r["kind"] == "button":
    return None
  return "binary_sensor" if r["kind"] == "bool" else "sensor"


def _entities(table):
  rows = [r for r in table if r["access"] != "off" and component(r)]
  keys = {r["key"] for r in rows}
  extras = [e for e in EXTRAS if e["key"] != "clock_drift" or "clock" in keys]
  return rows + [dict(e, table="", address=None, extra=True) for e in extras]


def configs(mqtt_cfg, table, device_info=None):
  """{discovery topic: payload} for every register with access read/write + the extra entities"""
  topic, node = mqtt_cfg["topic"], node_id(mqtt_cfg["topic"])
  info = device_info or {}
  device = {"identifiers": [node], "name": mqtt_cfg["device_name"], "manufacturer": "Nilan",
            "model": "Comfort 300 (CTS 602)"}
  if info.get("software"):
    device["sw_version"] = str(info["software"])
  if info.get("type") or info.get("bus_version") is not None:
    device["hw_version"] = f"{info.get('type') or 'CTS 602'}, Modbus bus version {info.get('bus_version', '?')}"
  availability = [{"topic": topic + "/lwt", "payload_available": "online", "payload_not_available": "offline"},
                  {"topic": topic + "/status", "payload_available": "online", "payload_not_available": "read error"}]
  out = {}
  for r in _entities(table):
    comp = component(r)
    key = r["key"]
    c = {"name": r["name"], "unique_id": f"{node}_{key}", "default_entity_id": f"{comp}.nilan_{key}",
         "availability": availability, "availability_mode": "all", "device": device,
         "json_attributes_topic": f"{topic}/attributes/{key}"}
    if comp != "button":
      c["state_topic"] = topic + "/state"
      c["value_template"] = "{{ value_json.%s }}" % key
    if comp in ("number", "select", "switch", "button"):
      c["command_topic"] = f"{topic}/set/{key}"
    if r.get("icon"):
      c["icon"] = r["icon"]
    cat = r.get("category")
    if cat == "diagnostic" or (cat == "config" and comp not in ("sensor", "binary_sensor")):
      c["entity_category"] = cat
    if r["kind"] == "number":
      if r.get("unit"):
        c["unit_of_measurement"] = r["unit"]
      if r.get("device_class"):
        c["device_class"] = r["device_class"]
      if comp == "sensor" and r.get("state_class"):
        c["state_class"] = r["state_class"]
      if comp == "number":
        c.update(min=r["min"], max=r["max"], step=r.get("step") or r.get("scale", 1), mode="box")
    elif r["kind"] == "bool":
      if comp == "binary_sensor":
        c.update(payload_on="ON", payload_off="OFF")
        if r.get("device_class"):
          c["device_class"] = r["device_class"]
      else:
        c.update(payload_on="ON", payload_off="OFF", state_on="ON", state_off="OFF")
    elif r["kind"] == "enum" and comp == "select":
      c["options"] = list(r["options"].values())
    elif comp == "button":
      c["payload_press"] = "PRESS"
    out[f"{mqtt_cfg['discovery_prefix']}/{comp}/{node}/{key}/config"] = json.dumps(c, ensure_ascii=False)
  return out


def attributes(mqtt_cfg, table):
  """{<topic>/attributes/<key>: JSON} with description, register and range for each announced entity"""
  out = {}
  for r in _entities(table):
    a = {"description": r.get("desc", "")}
    if r.get("address") is not None:
      a["register"] = f"{'input' if r['table'] == 'input' else 'holding'} register {r['address']}"
    rng = regs_mod.range_text(r) if r["access"] == "write" else ""
    if rng:
      a["allowed values"] = rng
    out[f"{mqtt_cfg['topic']}/attributes/{r['key']}"] = json.dumps(a, ensure_ascii=False)
  return out
