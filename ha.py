"""
Home Assistant MQTT discovery for the register table.

access read  -> sensor (number, enum, text) / binary_sensor (bool)
access write -> number / select / switch / button
Entity ids: <component>.nilan_<key>. All values come from one JSON state topic (<topic>/state).
An entity is available while the program runs (<topic>/lwt) and the unit answers (<topic>/status).
"""

import json
import re


def node_id(topic):
  """nilan/CTS602 -> nilan_cts602 (discovery node and unique_id prefix)"""
  return re.sub(r"[^a-z0-9_]", "_", topic.lower())


def component(r):
  if r["access"] == "write":
    return {"number": "number", "enum": "select", "bool": "switch", "button": "button"}.get(r["kind"], "sensor")
  if r["kind"] == "button":
    return None
  return "binary_sensor" if r["kind"] == "bool" else "sensor"


def configs(mqtt_cfg, table, sw_version=""):
  """{discovery topic: payload} for every register with access read/write"""
  topic, node = mqtt_cfg["topic"], node_id(mqtt_cfg["topic"])
  device = {"identifiers": [node], "name": mqtt_cfg["device_name"], "manufacturer": "Nilan",
            "model": "Comfort 300 (CTS 602)", "sw_version": sw_version}
  availability = [{"topic": topic + "/lwt", "payload_available": "online", "payload_not_available": "offline"},
                  {"topic": topic + "/status", "payload_available": "online", "payload_not_available": "read error"}]
  out = {}
  for r in table:
    comp = component(r) if r["access"] != "off" else None
    if comp is None:
      continue
    key = r["key"]
    c = {"name": r["name"], "unique_id": f"{node}_{key}", "default_entity_id": f"{comp}.nilan_{key}",
         "availability": availability, "availability_mode": "all", "device": device}
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
