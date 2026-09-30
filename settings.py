"""
Runtime settings, edited on the web page and saved in settings.json (mode 600: it holds the MQTT password).
Applied without a restart: new Modbus settings are used from the next transaction, new MQTT settings reconnect.

  modbus     serial port + Nilan unit address
  mqtt       broker, login, topic, Home Assistant discovery
  interval_s read every ... seconds
  registers  {key: {"access": off|read|write, "min": .., "max": ..}} changes to the built-in table (registers.py)
  custom     extra registers: [{key, name, table, address, kind (number|bool), scale, signed, unit, access, min, max, step}]

Only registers with access read/write are read; only access = write can be written (from HA or the page), and only
within min..max. Writing needs the register to be a holding register the spec allows to be written (built-in) or a
custom holding register with min and max.
"""

import copy
import json
import math
import os
import re
import threading

import logs
import registers as regs_mod

logger = logs.get("settings")

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
MIN_INTERVAL_S = 5
MAX_INTERVAL_S = 3600
TOPIC_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+){0,4}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]{1,253}$")
SCALES = (0.001, 0.01, 0.1, 1, 10)
ACCESS = ("off", "read", "write")
SECRET = "password"


def defaults():
  return {
    "modbus": {"port": "", "baudrate": 19200, "bytesize": 8, "parity": "E", "stopbits": 1, "unit": 30,
               "timeout": 0.5, "retries": 2, "gap_ms": 20},
    "mqtt": {"host": "", "port": 1883, "username": "", "password": "", "client_id": "nilan-mqtt",
             "topic": "nilan/CTS602", "discovery": True, "discovery_prefix": "homeassistant",
             "device_name": "Nilan Comfort 300"},
    "interval_s": 30,
    "registers": {},
    "custom": [],
    "schedule": {"enabled": False, "periods": []},
    "clock_sync": False,
  }


def _num(value, what, lo, hi, cast=float):
  try:
    v = cast(value)
  except (TypeError, ValueError):
    raise ValueError(f"{what} must be a number")
  if isinstance(v, float) and not math.isfinite(v) or not lo <= v <= hi:
    raise ValueError(f"{what} must be {lo}..{hi}")
  return v


def _limits(key, r, spec_min, spec_max, step):
  """min/max for a writable number, inside the spec limits"""
  lo = _num(r.get("min", spec_min), f"{key} min", spec_min, spec_max)
  hi = _num(r.get("max", spec_max), f"{key} max", spec_min, spec_max)
  if lo > hi:
    raise ValueError(f"{key}: min is above max")
  st = _num(r.get("step", step), f"{key} step", 0.001, 1000)
  return lo, hi, st


def _validate_custom(c, builtin_keys, seen):
  if not isinstance(c, dict):
    raise ValueError("each custom register must be an object")
  key = str(c.get("key", "")).strip().lower()
  if not regs_mod.KEY_RE.match(key) or key in builtin_keys or key in seen:
    raise ValueError(f"custom register key {key!r}: a-z, 0-9, _ (max 40) and not used already")
  seen.add(key)
  name = str(c.get("name") or key).strip()[:60]
  table = c.get("table")
  if table not in ("input", "holding"):
    raise ValueError(f"{key}: table must be input or holding")
  kind = c.get("kind", "number")
  if kind not in ("number", "bool"):
    raise ValueError(f"{key}: custom registers are number or bool")
  scale = _num(c.get("scale", 1), f"{key} scale", 0.001, 10)
  if scale not in SCALES:
    raise ValueError(f"{key}: scale must be one of {', '.join(map(str, SCALES))}")
  access = c.get("access", "read")
  if access not in ACCESS:
    raise ValueError(f"{key}: access must be off, read or write")
  unit = str(c.get("unit") or "").strip()[:12]
  out = {"key": key, "name": name, "table": table, "address": _num(c.get("address"), f"{key} address", 0, 65535, int),
         "kind": kind, "scale": scale if scale != int(scale) else int(scale), "signed": bool(c.get("signed", True)),
         "unit": unit, "access": access}
  if access == "write":
    if table != "holding":
      raise ValueError(f"{key}: only holding registers can be written")
    if kind == "number":
      if c.get("min") in (None, "") or c.get("max") in (None, ""):
        raise ValueError(f"{key}: a writable number needs min and max")
      lim = 32767 * scale if out["signed"] else 65535 * scale
      out["min"], out["max"], out["step"] = _limits(key, c, -lim if out["signed"] else 0, lim, c.get("step") or scale)
  return out


def _validate_schedule(sch):
  """{"enabled": bool, "periods": [{"days": [0..6 = Mon..Sun], "start": "HH:MM", "step": "0".."4" | None,
  "temp": 15..28 | None}]}; sorted by start time"""
  if not isinstance(sch, dict):
    raise ValueError("schedule must be an object")
  periods = sch.get("periods") or []
  if not isinstance(periods, list) or len(periods) > 50:
    raise ValueError("schedule: at most 50 periods")
  out = []
  for i, p in enumerate(periods, 1):
    if not isinstance(p, dict):
      raise ValueError(f"schedule period {i}: must be an object")
    days = p.get("days") or []
    if not isinstance(days, list) or not days or any(d not in range(7) for d in days):
      raise ValueError(f"schedule period {i}: pick at least one day")
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(p.get("start", "")).strip())
    if not m:
      raise ValueError(f"schedule period {i}: start time HH:MM")
    step = p.get("step")
    step = None if step in (None, "") else str(step)
    if step is not None and step not in regs_mod.STEPS.values():
      raise ValueError(f"schedule period {i}: step 0-4 or empty")
    temp = p.get("temp")
    temp = None if temp in (None, "") else _num(temp, f"schedule period {i} temperature", 15, 28)
    if step is None and temp is None:
      raise ValueError(f"schedule period {i}: set a step, a temperature or both")
    out.append({"days": sorted(set(days)), "start": f"{int(m.group(1)):02d}:{m.group(2)}", "step": step, "temp": temp})
  out.sort(key=lambda p: p["start"])
  return {"enabled": bool(sch.get("enabled", False)), "periods": out}


def validate(s, old=None):
  """Clean copy of s. An empty or missing MQTT password keeps the one in `old`."""
  if not isinstance(s, dict):
    raise ValueError("settings must be an object")
  d = defaults()
  out = copy.deepcopy(d)

  m = dict(d["modbus"], **(s.get("modbus") or {}))
  port = str(m.get("port") or "").strip()
  if port and port != "simulate" and not re.match(r"^/dev/[A-Za-z0-9_./:\-]+$", port):
    raise ValueError("serial port must be a /dev/... path (best: /dev/serial/by-id/...) or 'simulate'")
  out["modbus"] = {
    "port": port,
    "baudrate": _num(m["baudrate"], "baud", 1200, 115200, int),
    "bytesize": _num(m["bytesize"], "data bits", 7, 8, int),
    "parity": str(m["parity"]).upper(),
    "stopbits": _num(m["stopbits"], "stop bits", 1, 2, int),
    "unit": _num(m["unit"], "unit address", 1, 247, int),
    "timeout": _num(m["timeout"], "timeout", 0.1, 5),
    "retries": _num(m["retries"], "retries", 0, 5, int),
    "gap_ms": _num(m["gap_ms"], "gap between frames", 0, 1000, int),
  }
  if out["modbus"]["baudrate"] not in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200):
    raise ValueError("baud must be 1200, 2400, 4800, 9600, 19200, 38400, 57600 or 115200")
  if out["modbus"]["parity"] not in ("N", "E", "O"):
    raise ValueError("parity must be N, E or O")

  q = dict(d["mqtt"], **(s.get("mqtt") or {}))
  host = str(q.get("host") or "").strip()
  if host and not HOST_RE.match(host):
    raise ValueError("MQTT broker: host name or IP address")
  password = q.get("password")
  if password in (None, "") and old:
    password = old["mqtt"]["password"]
  topic = str(q.get("topic") or "").strip().strip("/")
  prefix = str(q.get("discovery_prefix") or "").strip().strip("/")
  if not TOPIC_RE.match(topic) or not TOPIC_RE.match(prefix):
    raise ValueError("MQTT topic / discovery prefix: letters, digits, _ -, separated by /")
  client_id = str(q.get("client_id") or "").strip()
  if not re.match(r"^[A-Za-z0-9_\-]{1,40}$", client_id):
    raise ValueError("MQTT client id: letters, digits, _ - (max 40)")
  out["mqtt"] = {"host": host, "port": _num(q["port"], "MQTT port", 1, 65535, int),
                 "username": str(q.get("username") or "").strip()[:100], "password": str(password or "")[:200],
                 "client_id": client_id, "topic": topic, "discovery": bool(q.get("discovery", True)),
                 "discovery_prefix": prefix, "device_name": str(q.get("device_name") or "Nilan").strip()[:60]}

  out["interval_s"] = _num(s.get("interval_s", d["interval_s"]), "interval", MIN_INTERVAL_S, MAX_INTERVAL_S, int)

  builtin = regs_mod.by_key()
  overrides = {}
  for key, r in (s.get("registers") or {}).items():
    if key not in builtin or not isinstance(r, dict):
      continue          # registers removed from the table in a newer version: drop the old setting
    b = builtin[key]
    access = r.get("access", b["access"])
    if access not in ACCESS:
      raise ValueError(f"{key}: access must be off, read or write")
    if access == "write" and not b.get("writable"):
      raise ValueError(f"{key} ({b['table']} {b['address']}) can't be written")
    o = {"access": access}
    if b["kind"] == "number" and b.get("writable"):
      o["min"], o["max"], _ = _limits(key, r, b["min"], b["max"], b["step"])
      if o["min"] == b["min"] and o["max"] == b["max"]:
        del o["min"], o["max"]
    if o != {"access": b["access"]}:
      overrides[key] = o
  out["registers"] = overrides

  seen = set()
  custom = s.get("custom") or []
  if not isinstance(custom, list) or len(custom) > 100:
    raise ValueError("custom registers: a list of at most 100")
  out["custom"] = [_validate_custom(c, builtin, seen) for c in custom]
  out["schedule"] = _validate_schedule(s.get("schedule") or {})
  out["clock_sync"] = bool(s.get("clock_sync", False))
  return out


def effective(s):
  """The register table in use: built-in + changes + custom, each with its access"""
  table = []
  for b in regs_mod.BUILTIN:
    r = copy.deepcopy(b)
    r.update(s["registers"].get(b["key"], {}))
    r["builtin"] = True
    table.append(r)
  for c in s["custom"]:
    r = copy.deepcopy(c)
    r["builtin"] = False
    r["writable"] = r["table"] == "holding" and (r["kind"] == "bool" or "min" in r)
    table.append(r)
  return table


def public(s):
  """Settings for the page: without the MQTT password"""
  p = copy.deepcopy(s)
  p["mqtt"]["password_set"] = bool(p["mqtt"].pop(SECRET))
  return p


# ---- readable change list for the log ("mqtt.host: a -> b") ----
def _flat(value, path=""):
  if isinstance(value, dict):
    for k, v in value.items():
      yield from _flat(v, f"{path}.{k}" if path else str(k))
  elif isinstance(value, list) and value and all(isinstance(x, dict) and "key" in x for x in value):
    for x in value:
      yield from _flat({k: v for k, v in x.items() if k != "key"}, f"{path}.{x['key']}")
  else:
    yield path, value


def describe_changes(old, new, most=12):
  missing = object()
  a, b = dict(_flat(old)), dict(_flat(new))
  out = []
  for k in list(a) + [k for k in b if k not in a]:
    va, vb = a.get(k, missing), b.get(k, missing)
    if va != vb:
      if k.endswith("." + SECRET):
        out.append(f"{k} changed")
      else:
        out.append(f"{k}: {'(none)' if va is missing else va} -> {'(none)' if vb is missing else vb}")
  return out[:most] + ([f"and {len(out) - most} more"] if len(out) > most else [])


class Settings:
  def __init__(self, path=SETTINGS_FILE):
    self.__path = path
    self.__lock = threading.Lock()
    self.__listeners = []
    self.__s = validate(defaults())
    try:
      with open(path, encoding="utf-8") as f:
        self.__s = validate(json.load(f))
      logger.info(f"Settings loaded from {path}")
    except FileNotFoundError:
      logger.info(f"No {path}; using defaults")
    except (ValueError, json.JSONDecodeError) as e:
      logger.error(f"Ignoring {path}: {e}; using defaults")

  def get(self):
    with self.__lock:
      return copy.deepcopy(self.__s)

  def on_change(self, callback):
    self.__listeners.append(callback)

  def update(self, new, who=""):
    """Validate, save and apply; logs who changed what"""
    with self.__lock:
      old = self.__s
    clean = validate(new, old)
    with self.__lock:
      tmp = self.__path + ".tmp"
      fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
      with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
      os.replace(tmp, self.__path)
      self.__s = clean
    changes = "; ".join(describe_changes(old, clean)) or "no changes"
    logger.info(f"Settings changed{' by ' + who if who else ''}: {changes}")
    for cb in self.__listeners:
      cb(old, clean)
    return copy.deepcopy(clean)
