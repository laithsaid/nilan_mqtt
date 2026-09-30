"""
Register table of the Nilan CTS 602 controller (Comfort 300, device type 13) and value conversion.

Sources: Nilan "CTS 602 Modbus" register list as used by github.com/veista/nilan (registers.py, device.py), checked
against our unit on 2026-09-30 (bus version 5): the registers below answer; many others (1102-1105, 1206-1209 holding,
3000+, 4000+) give exception 2 on this unit and are left out.

Each register:
  key       MQTT / Home Assistant key (sensor.nilan_<key>)
  name      shown in HA and on the page
  table     "input" (read only) or "holding"
  address   Modbus register number
  kind      number | enum | bool | text | button
  scale     number: value = raw * scale  (0.01 for °C and %, 1 otherwise)
  signed    number: raw is int16 (default) or uint16
  mask      number: only these bits (alarm count = low 2 bits)
  count     text: number of registers (2 characters each, low byte first)
  options   enum: {raw: label}
  press     button: value written when pressed
  min, max, step   writable numbers (in engineering units)
  writable  the spec allows writing it (only holding registers). The page can set access = write only for these.
  access    default: off (not read), read, write
  unit, device_class, state_class, icon, category (diagnostic / config)
"""

import re

STEPS = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4"}
MODES = {0: "Off", 1: "Heat", 2: "Cool", 3: "Auto"}
USER_FUNCTIONS = {0: "None", 1: "Extended", 2: "Supply air", 3: "Extract air", 4: "External offset", 5: "Ventilate"}
CONTROL_STATES = {0: "Off", 1: "Shift", 2: "Stop", 3: "Start", 4: "Standby", 5: "Ventilation stop", 6: "Ventilation",
                  7: "Heating", 8: "Cooling", 9: "Hot water", 10: "Legionella", 11: "Cooling + hot water",
                  12: "Central heating", 13: "Defrost", 14: "Frost secure", 15: "Service", 16: "Alarm",
                  17: "Heating + hot water"}
ALARMS = {0: "None", 1: "E01 Hardware error", 2: "E02 Alarm timeout", 3: "E03 Fire alarm", 4: "E04 Pressure switch",
          5: "E05 Inspection door open", 6: "E06 De-icing error", 7: "E07 Frost thermostat", 8: "E08 Frost thermostat",
          9: "E09 Boiler over temperature", 10: "E10 After-heater over temperature",
          11: "E11 Low flow over electric heater", 12: "E12 Fan motor thermal switch",
          13: "E13 Water heater over temperature", 14: "E14 Sensor defective", 15: "E15 Room temperature too low",
          16: "E16 Software error", 17: "E17 Watchdog", 18: "E18 Database changed", 19: "E19 Change air filter",
          20: "E20 Legionella treatment error", 21: "E21 Check date and time", 22: "E22 Air temperature error",
          23: "E23 Hot water temperature error", 24: "E24 Central heating temperature error",
          25: "E25 Modem error", 26: "E26 Network error", 70: "E70 Anode error", 71: "E71 De-icing heat exchanger",
          72: "E72 Evaporator temperature low", 90: "E90 Slave IO", 91: "E91 Option module missing",
          92: "E92 Backup error", 95: "E95 Software update rejected", 96: "E96 Damper self-test error"}
ALARMS.update({n: f"E{n:02d} Temperature sensor error" for n in range(27, 59)})
DEVICE_TYPES = {2: "Comfort light", 3: "Comfort Polar", 13: "COMFORT", 31: "COMFORTn", 33: "COMBI 300 N"}
AIR_EXCHANGE = {0: "Energy", 1: "Comfort", 2: "Comfort water"}
COOL_OFFSET = {0: "Cooling off", 1: "+0 °C", 2: "+1 °C", 3: "+2 °C", 4: "+3 °C", 5: "+4 °C", 6: "+5 °C",
               7: "+7 °C", 8: "+10 °C"}

T = dict(kind="number", scale=0.01, unit="°C", device_class="temperature", state_class="measurement")
PCT = dict(kind="number", scale=0.01, unit="%", state_class="measurement")
DIAG = dict(category="diagnostic")
CONF = dict(category="config", writable=True)


def _r(key, name, table, address, access="read", **kw):
  return dict(key=key, name=name, table=table, address=address, access=access, **kw)


BUILTIN = [
  # ---- input registers (read only) ----
  _r("bus_version", "Modbus bus version", "input", 0, kind="number", scale=1, **DIAG),
  _r("software_version", "Software version", "input", 1, kind="text", count=3, **DIAG),
  _r("user_function_1_input", "User function 1 input", "input", 100, kind="bool", icon="mdi:gesture-tap-button"),
  _r("user_function_2_input", "User function 2 input", "input", 113, kind="bool", icon="mdi:gesture-tap-button"),
  _r("input_air_filter", "Air filter input", "input", 101, "off", kind="bool", **DIAG),
  _r("input_door_open", "Door open input", "input", 102, "off", kind="bool", **DIAG),
  _r("input_smoke", "Smoke input", "input", 103, "off", kind="bool", **DIAG),
  _r("input_motor_thermo", "Motor thermal switch input", "input", 104, "off", kind="bool", **DIAG),
  _r("input_frost_overheat", "Frost / overheat input", "input", 105, "off", kind="bool", **DIAG),
  _r("t0_controller", "Controller temperature (T0)", "input", 200, **T, **DIAG),
  _r("t1_intake", "Intake temperature (T1)", "input", 201, "off", **T),
  _r("t2_inlet", "Inlet temperature (T2)", "input", 202, "off", **T),
  _r("t3_exhaust", "Extract air temperature (T3)", "input", 203, **T),
  _r("t4_outlet", "Exhaust air temperature (T4)", "input", 204, **T),
  _r("t7_inlet", "Supply air temperature (T7)", "input", 207, **T),
  _r("t8_outdoor", "Outdoor temperature (T8)", "input", 208, **T),
  _r("t10_extern", "External temperature (T10)", "input", 210, "off", **T),
  _r("t15_room", "Panel room temperature (T15)", "input", 215, **T),
  _r("humidity", "Humidity", "input", 221, **dict(PCT, device_class="humidity")),
  _r("co2", "CO2", "input", 222, "off", kind="number", scale=1, unit="ppm", device_class="carbon_dioxide",
     state_class="measurement"),
  _r("alarm_count", "Active alarms", "input", 400, kind="number", scale=1, mask=0x03, icon="mdi:alarm-light"),
  _r("alarm_1", "Alarm 1", "input", 401, kind="enum", options=ALARMS, icon="mdi:alert"),
  _r("alarm_2", "Alarm 2", "input", 404, kind="enum", options=ALARMS, icon="mdi:alert"),
  _r("alarm_3", "Alarm 3", "input", 407, kind="enum", options=ALARMS, icon="mdi:alert"),
  _r("running", "Running", "input", 1000, kind="bool", device_class="running"),
  _r("mode_actual", "Operating mode (actual)", "input", 1001, kind="enum", options={**MODES, 4: "Service"},
     icon="mdi:cog"),
  _r("control_state", "Control state", "input", 1002, kind="enum", options=CONTROL_STATES, icon="mdi:state-machine"),
  _r("time_in_state", "Time in control state", "input", 1003, kind="number", scale=1, signed=False, unit="s",
     device_class="duration", state_class="measurement", **DIAG),
  _r("summer", "Summer mode", "input", 1200, kind="bool", icon="mdi:weather-sunny"),
  _r("supply_temp_target", "Supply air temperature target", "input", 1201, **T),
  _r("control_temp", "Control temperature", "input", 1202, **T),
  _r("room_temp_used", "Room temperature (used)", "input", 1203, "off", **T),
  _r("exchanger_efficiency", "Heat exchanger efficiency", "input", 1204, **dict(PCT, icon="mdi:swap-horizontal")),
  _r("heat_capacity_set", "After-heating capacity set", "input", 1205, "off", **dict(PCT, icon="mdi:radiator")),
  _r("heat_capacity", "After-heating capacity", "input", 1206, **dict(PCT, icon="mdi:radiator")),
  _r("display_line_1", "Display line 1", "input", 2002, kind="text", count=4, icon="mdi:monitor", **DIAG),
  _r("display_line_2", "Display line 2", "input", 2007, kind="text", count=4, icon="mdi:monitor", **DIAG),

  # ---- holding registers: status ----
  _r("device_type", "Device type", "holding", 1000, kind="enum", options=DEVICE_TYPES, **DIAG),
  _r("exhaust_fan", "Extract fan speed", "holding", 200, **dict(PCT, icon="mdi:fan")),
  _r("supply_fan", "Supply fan speed", "holding", 201, **dict(PCT, icon="mdi:fan")),
  _r("weekly_program", "Weekly program", "holding", 500, kind="number", scale=1, icon="mdi:calendar-week", **DIAG),
  _r("service_mode", "Service mode", "holding", 1005, "off", kind="number", scale=1, **DIAG),
  _r("service_capacity", "Service capacity", "holding", 1006, "off", **dict(PCT, **DIAG)),

  # ---- holding registers: settings Home Assistant may change ----
  _r("run", "Run", "holding", 1001, "write", kind="bool", writable=True, icon="mdi:power"),
  _r("mode", "Operating mode", "holding", 1002, "write", kind="enum", options=MODES, writable=True, icon="mdi:cog"),
  _r("ventilation_step", "Ventilation step", "holding", 1003, "write", kind="enum", options=STEPS, writable=True,
     icon="mdi:fan"),
  _r("temp_setpoint", "Room temperature setpoint", "holding", 1004, "write", **dict(T, state_class=None),
     writable=True, min=15, max=28, step=0.5, icon="mdi:thermostat"),
  _r("alarm_reset", "Reset alarms", "holding", 400, "write", kind="button", press=255, writable=True,
     icon="mdi:alarm-off", category="config"),

  _r("user_function_1", "User function 1 active", "holding", 600, "read", kind="bool", writable=True,
     icon="mdi:gesture-tap-button"),
  _r("user_function_1_mode", "User function 1", "holding", 601, "write", kind="enum", options=USER_FUNCTIONS, **CONF),
  _r("user_function_1_time", "User function 1 time", "holding", 602, "write", kind="number", scale=1, unit="min",
     min=0, max=480, step=15, **CONF),
  _r("user_function_1_step", "User function 1 ventilation step", "holding", 603, "write", kind="enum",
     options=STEPS, **CONF),
  _r("user_function_1_temp", "User function 1 temperature", "holding", 604, "write", kind="number", scale=1,
     unit="°C", device_class="temperature", min=5, max=30, step=1, **CONF),
  _r("user_function_1_offset", "User function 1 offset", "holding", 605, "write", kind="number", scale=1,
     unit="°C", min=-10, max=10, step=1, **CONF),
  _r("user_function_2", "User function 2 active", "holding", 610, "read", kind="bool", writable=True,
     icon="mdi:gesture-tap-button"),
  _r("user_function_2_mode", "User function 2", "holding", 611, "write", kind="enum",
     options={**USER_FUNCTIONS, 6: "Cooker hood"}, **CONF),
  _r("user_function_2_time", "User function 2 time", "holding", 612, "write", kind="number", scale=1, unit="min",
     min=0, max=480, step=15, **CONF),
  _r("user_function_2_step", "User function 2 ventilation step", "holding", 613, "write", kind="enum",
     options=STEPS, **CONF),
  _r("user_function_2_temp", "User function 2 temperature", "holding", 614, "write", kind="number", scale=1,
     unit="°C", device_class="temperature", min=5, max=30, step=1, **CONF),
  _r("user_function_2_offset", "User function 2 offset", "holding", 615, "write", kind="number", scale=1,
     unit="°C", min=-10, max=10, step=1, **CONF),

  _r("air_exchange_mode", "Air exchange mode", "holding", 1100, "read", kind="enum", options=AIR_EXCHANGE, **CONF),
  _r("cooling_step", "Cooling ventilation step", "holding", 1101, "read", kind="enum",
     options={0: "No change", 1: "1", 2: "2", 3: "3", 4: "4"}, **CONF),
  _r("cooling_offset", "Cooling setpoint offset", "holding", 1200, "read", kind="enum", options=COOL_OFFSET, **CONF),
  _r("supply_min_summer", "Min supply air temperature summer", "holding", 1201, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF),
  _r("supply_min_winter", "Min supply air temperature winter", "holding", 1202, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF),
  _r("supply_max_summer", "Max supply air temperature summer", "holding", 1203, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF),
  _r("supply_max_winter", "Max supply air temperature winter", "holding", 1204, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF),
  _r("summer_changeover", "Summer changeover temperature", "holding", 1205, "write",
     **dict(T, state_class=None), min=5, max=30, step=0.5, **CONF),
  _r("humidity_low_step", "Low humidity ventilation step", "holding", 1910, "write", kind="enum", options=STEPS,
     **CONF),
  _r("humidity_high_step", "High humidity ventilation step", "holding", 1911, "write", kind="enum",
     options={0: "0", 2: "2", 3: "3", 4: "4"}, **CONF),
  _r("humidity_limit", "Humidity limit", "holding", 1912, "write", **dict(PCT, state_class=None), min=15, max=45,
     step=1, **CONF),
  _r("humidity_max_time", "High humidity max time", "holding", 1913, "write", kind="number", scale=1, unit="min",
     min=0, max=180, step=1, **CONF),
  _r("co2_high_step", "CO2 high ventilation step", "holding", 1920, "off", kind="enum",
     options={0: "0", 2: "2", 3: "3", 4: "4"}, **CONF),
  _r("co2_low_limit", "CO2 low limit", "holding", 1921, "off", kind="number", scale=1, unit="ppm", min=400, max=750,
     step=10, **CONF),
  _r("co2_high_limit", "CO2 high limit", "holding", 1922, "off", kind="number", scale=1, unit="ppm", min=650,
     max=2500, step=10, **CONF),
]

KINDS = ("number", "enum", "bool", "text", "button")
KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def decimals(scale):
  """0.01 -> 2, 0.1 -> 1, 1 -> 0"""
  text = f"{scale:.10f}".rstrip("0")
  return len(text.split(".")[1]) if "." in text else 0


def span(r):
  return r.get("count", 1) if r["kind"] == "text" else 1


def decode(r, words):
  """Raw 16-bit words -> value for MQTT / the page"""
  kind = r["kind"]
  if kind == "text":
    chars = []
    for w in words:
      for b in (w & 0xFF, w >> 8):
        if b == 0:
          return "".join(chars).rstrip()
        chars.append("°" if b == 0xDF else chr(b) if 32 <= b < 127 else "?")
    return "".join(chars).rstrip()
  raw = words[0]
  if kind == "bool":
    return "ON" if raw else "OFF"
  if kind == "enum":
    return r["options"].get(raw, f"Unknown ({raw})")
  if kind == "button":
    return None
  if r.get("mask"):
    raw &= r["mask"]
  elif r.get("signed", True) and raw >= 0x8000:
    raw -= 0x10000
  scale = r.get("scale", 1)
  return round(raw * scale, decimals(scale)) if scale != 1 else raw


def encode(r, value):
  """Value from HA / the page -> raw word. Raises ValueError when not allowed."""
  kind = r["kind"]
  text = str(value).strip()
  if kind == "button":
    return int(r["press"])
  if kind == "bool":
    if text.upper() in ("ON", "1", "TRUE"):
      return 1
    if text.upper() in ("OFF", "0", "FALSE"):
      return 0
    raise ValueError(f"{r['key']}: expected ON or OFF, got {text!r}")
  if kind == "enum":
    for raw, label in r["options"].items():
      if text == label or text == str(raw):
        return int(raw)
    raise ValueError(f"{r['key']}: {text!r} is not one of {', '.join(r['options'].values())}")
  if kind != "number":
    raise ValueError(f"{r['key']}: {kind} registers can't be written")
  try:
    v = float(text)
  except ValueError:
    raise ValueError(f"{r['key']}: {text!r} is not a number")
  if v != v or not r["min"] <= v <= r["max"]:
    raise ValueError(f"{r['key']}: {text} is outside {r['min']}..{r['max']}")
  raw = int(round(v / r.get("scale", 1)))
  if r.get("signed", True):
    if not -0x8000 <= raw <= 0x7FFF:
      raise ValueError(f"{r['key']}: {text} does not fit the register")
    return raw & 0xFFFF
  if not 0 <= raw <= 0xFFFF:
    raise ValueError(f"{r['key']}: {text} does not fit the register")
  return raw


def by_key():
  return {r["key"]: r for r in BUILTIN}
