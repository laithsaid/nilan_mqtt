"""
Register table of the Nilan CTS 602 controller (Comfort 300, device type 13) and value conversion.

Sources: Nilan "CTS602 Modbus protocol" (version 3.00, 19-10-2016, software 2.35) and github.com/veista/nilan, checked
against our unit on 2026-09-30 (software 2.21, bus version 5). Registers that answer "exception 2" on our unit (e.g. IR
1100-1104 filter days, HR 1102-1105 damper test, HR 1206-1207 night cooling, HR 4000+ incl. the week program editor)
are left out.

Each register:
  key       MQTT / Home Assistant key (sensor.nilan_<key>)
  name      shown in HA and on the page
  desc      what it is, what the values mean, what a change does (page + HA attribute "description")
  table     "input" (read only) or "holding"
  address   Modbus register number
  kind      number | enum | bool | text | button | clock
  scale     number: value = raw * scale  (0.01 for °C and %, 1 otherwise)
  signed    number: raw is int16 (default) or uint16
  mask      number: only these bits (alarm count = low 2 bits)
  count     text / clock: number of registers (text: 2 characters each, low byte first)
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
# Never use the label "None" (or "True" / "False"): Home Assistant reads such a template result as "no value" and the
# entity shows "unknown".
USER_FUNCTIONS = {0: "Not used", 1: "Extended", 2: "Supply air", 3: "Extract air", 4: "External offset", 5: "Ventilate"}
CONTROL_STATES = {0: "Off", 1: "Shift", 2: "Stop", 3: "Start", 4: "Standby", 5: "Ventilation stop", 6: "Ventilation",
                  7: "Heating", 8: "Cooling", 9: "Hot water", 10: "Legionella", 11: "Cooling + hot water",
                  12: "Central heating", 13: "Defrost", 14: "Frost secure", 15: "Service", 16: "Alarm",
                  17: "Heating + hot water"}
ALARMS = {0: "No alarm", 1: "E01 Hardware error", 2: "E02 Alarm timeout", 3: "E03 Fire alarm", 4: "E04 Pressure switch",
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
for _n in range(27, 59):
  ALARMS[_n] = f"E{_n:02d} Sensor T{(_n - 27) // 2 + 1} {'shorted' if _n % 2 else 'disconnected'}"
DEVICE_TYPES = {2: "Comfort light", 3: "Comfort Polar", 13: "COMFORT", 31: "COMFORTn", 33: "COMBI 300 N"}
AIR_EXCHANGE = {0: "Energy", 1: "Comfort", 2: "Comfort water"}
COOL_OFFSET = {0: "Cooling off", 1: "+0 °C", 2: "+1 °C", 3: "+2 °C", 4: "+3 °C", 5: "+4 °C", 6: "+5 °C",
               7: "+7 °C", 8: "+10 °C"}
WEEK_PROGRAMS = {0: "No program", 1: "Program 1", 2: "Program 2", 3: "Program 3"}   # 4 = Erase: deliberately left out

T = dict(kind="number", scale=0.01, unit="°C", device_class="temperature", state_class="measurement")
PCT = dict(kind="number", scale=0.01, unit="%", state_class="measurement")
DIAG = dict(category="diagnostic")
CONF = dict(category="config", writable=True)
STEP_TEXT = ("Steps: 0 = fans stopped (only for short periods: no fresh air, moisture builds up), 1 = lowest, "
             "4 = highest. The fan speed of each step is set by the installer.")


def _r(key, name, table, address, access="read", desc="", **kw):
  return dict(key=key, name=name, desc=desc, table=table, address=address, access=access, **kw)


BUILTIN = [
  # ---- device ----
  _r("bus_version", "Modbus bus version", "input", 0, kind="number", scale=1, **DIAG,
     desc="Version of the controller's Modbus register map (5 on our unit). Newer versions have more registers."),
  _r("software_version", "Software version", "input", 1, kind="text", count=3, **DIAG,
     desc="Controller software version (major, minor, release as ASCII text; IR 1-3). The panel shows the same number "
          "in its service/info menu."),
  _r("device_type", "Device type", "holding", 1000, kind="enum", options=DEVICE_TYPES, **DIAG,
     desc="Machine type the controller is set up for (13 = COMFORT). Set by the installer; never written here."),

  # ---- temperatures and air quality ----
  _r("t0_controller", "Controller temperature (T0)", "input", 200, **T, **DIAG,
     desc="Temperature on the controller board inside the unit. Diagnostic only."),
  _r("t1_intake", "Intake temperature (T1)", "input", 201, "off", **T,
     desc="Fresh air intake temperature. Not fitted on a Comfort 300 (reads 0)."),
  _r("t2_inlet", "Inlet temperature before heater (T2)", "input", 202, "off", **T,
     desc="Supply air before the after-heater. Not fitted on our unit (reads 0)."),
  _r("t3_exhaust", "Extract air temperature (T3)", "input", 203, **T,
     desc="Air taken out of the rooms (kitchen, bath, utility), measured as it enters the unit. Close to the average "
          "room temperature; used for the room control when no room sensor is selected."),
  _r("t4_outlet", "Exhaust air temperature (T4)", "input", 204, **T,
     desc="Air leaving the house after it has given its heat to the fresh air in the heat exchanger. The colder "
          "this is (compared with T3), the more heat was recovered."),
  _r("t7_inlet", "Supply air temperature (T7)", "input", 207, **T,
     desc="Fresh air blown into the living rooms and bedrooms, after the heat exchanger and after-heater. The unit "
          "controls this towards the 'supply air temperature target', inside the min/max supply limits."),
  _r("t8_outdoor", "Outdoor temperature (T8)", "input", 208, **T,
     desc="Outdoor air as it enters the unit (fresh air intake). Decides summer/winter mode and frost protection."),
  _r("t10_extern", "External room temperature (T10)", "input", 210, "off", **T,
     desc="Optional external room sensor wired to the unit. Not connected on our unit (reads -40 °C)."),
  _r("t15_room", "Panel room temperature (T15)", "input", 215, **T,
     desc="Temperature measured by the CTS 602 control panel on the wall."),
  _r("humidity", "Humidity", "input", 221, **dict(PCT, device_class="humidity"),
     desc="Relative humidity of the extract air (from the rooms). Above the humidity limit the unit switches to the "
          "high humidity ventilation step."),
  _r("co2", "CO2", "input", 222, "off", kind="number", scale=1, unit="ppm", device_class="carbon_dioxide",
     state_class="measurement", desc="CO2 in the extract air. Needs the optional CO2 sensor; our unit has none (0)."),

  # ---- status ----
  _r("running", "Running", "input", 1000, kind="bool", device_class="running",
     desc="Actual on/off state. ON = the unit runs (also when started by a user function while 'Run' is off)."),
  _r("mode_actual", "Operating mode (actual)", "input", 1001, kind="enum", options={**MODES, 4: "Service"},
     icon="mdi:cog", desc="The mode the unit is really in: Off, Heat, Cool, Auto or Service. See 'Operating mode'."),
  _r("control_state", "Control state", "input", 1002, kind="enum", options=CONTROL_STATES, icon="mdi:state-machine",
     desc="What the controller is doing right now, e.g. Ventilation, Heating (after-heater allowed/active), Cooling, "
          "Defrost (heat exchanger de-icing in frost), Frost secure, Standby, Alarm."),
  _r("time_in_state", "Time in control state", "input", 1003, kind="number", scale=1, signed=False, unit="s",
     device_class="duration", state_class="measurement", **DIAG,
     desc="Seconds since the control state last changed (counts up to 65535 s ≈ 18 h)."),
  _r("summer", "Summer mode", "input", 1200, kind="bool", icon="mdi:weather-sunny",
     desc="ON when the controller is in summer mode (outdoor temperature above the 'summer changeover temperature'). "
          "Summer uses the summer supply air limits and allows bypass/cooling."),
  _r("supply_temp_target", "Supply air temperature target", "input", 1201, **T,
     desc="The supply air temperature (T7) the controller is aiming for now, calculated from the room setpoint and "
          "the room/extract temperature, limited by the min/max supply limits."),
  _r("control_temp", "Control temperature", "input", 1202, **T,
     desc="The temperature the room control uses as 'actual room temperature' (usually T3 extract air)."),
  _r("room_temp_used", "Room temperature (used)", "input", 1203, "off", **T,
     desc="Actual room temperature from T15 or T10, if one of these is selected as room sensor."),
  _r("exchanger_efficiency", "Heat exchanger efficiency", "input", 1204, **dict(PCT, icon="mdi:swap-horizontal"),
     desc="How much of the extract air's heat the heat exchanger gives to the fresh air (dry efficiency, from "
          "T3, T4 and T8). About 80-95 % is normal for a counter-flow exchanger; low values in winter can mean "
          "bypass open, defrost or a dirty exchanger."),
  _r("heat_capacity_set", "After-heating capacity requested", "input", 1205, "off", **dict(PCT, icon="mdi:radiator"),
     desc="How much after-heating the controller asks for (0-100 %)."),
  _r("heat_capacity", "After-heating capacity", "input", 1206, **dict(PCT, icon="mdi:radiator"),
     desc="Actual after-heater output (0-100 %). 0 when the heat exchanger alone reaches the supply air target."),
  _r("user_function_1_input", "User function 1 input", "input", 100, kind="bool", icon="mdi:gesture-tap-button",
     desc="ON while the user function 1 input (a switch or button wired to the unit) is active."),
  _r("user_function_2_input", "User function 2 input", "input", 113, kind="bool", icon="mdi:gesture-tap-button",
     desc="ON while the user function 2 input (e.g. cooker hood contact) is active."),
  _r("input_air_filter", "Air filter input", "input", 101, "off", kind="bool", **DIAG,
     desc="Air filter pressure switch input. Reads ON on our unit without a filter alarm (contact wiring), so it is "
          "off by default; watch the alarms instead (E19)."),
  _r("input_door_open", "Door contact input", "input", 102, "off", kind="bool", **DIAG,
     desc="Inspection door contact (not fitted on all units)."),
  _r("input_smoke", "Fire/smoke input", "input", 103, "off", kind="bool", **DIAG, desc="Fire/smoke thermostat input."),
  _r("input_motor_thermo", "Motor thermal fuse input", "input", 104, "off", kind="bool", **DIAG,
     desc="Fan motor thermal fuse input."),
  _r("input_frost_overheat", "Frost / overheat input", "input", 105, "off", kind="bool", **DIAG,
     desc="Heating surface frost/overheat thermostat. Reads ON on our unit without an alarm (NC contact)."),
  _r("alarm_count", "Active alarms", "input", 400, kind="number", scale=1, mask=0x03, icon="mdi:alarm-light",
     desc="Number of alarms in the alarm list (0-3). Details in Alarm 1-3; clear them with 'Reset alarms' after "
          "fixing the cause (e.g. change the filter for E19)."),
  _r("alarm_1", "Alarm 1", "input", 401, kind="enum", options=ALARMS, icon="mdi:alert",
     desc="First alarm in the list: code and text (see the Nilan alarm list). 'No alarm' when the list is empty."),
  _r("alarm_2", "Alarm 2", "input", 404, kind="enum", options=ALARMS, icon="mdi:alert", desc="Second alarm in the list."),
  _r("alarm_3", "Alarm 3", "input", 407, kind="enum", options=ALARMS, icon="mdi:alert", desc="Third alarm in the list."),
  _r("display_line_1", "Display line 1", "input", 2002, kind="text", count=4, icon="mdi:monitor", **DIAG,
     desc="What the control panel shows on line 1 right now (e.g. 'AUTO 1' = mode Auto, step 1)."),
  _r("display_line_2", "Display line 2", "input", 2007, kind="text", count=4, icon="mdi:monitor", **DIAG,
     desc="What the control panel shows on line 2 right now (e.g. '>1< 22°C')."),

  # ---- outputs (holding registers, read only here) ----
  _r("exhaust_fan", "Extract fan speed", "holding", 200, **dict(PCT, icon="mdi:fan"),
     desc="Speed of the fan that takes air out of the rooms (0-100 %). Set by the ventilation step, humidity/user "
          "functions and defrost."),
  _r("supply_fan", "Supply fan speed", "holding", 201, **dict(PCT, icon="mdi:fan"),
     desc="Speed of the fan that blows fresh air into the rooms (0-100 %). Usually a bit below the extract fan so "
          "the house stays at a slight underpressure."),
  _r("heater_output", "After-heater output", "holding", 202, **dict(PCT, icon="mdi:radiator"),
     desc="Output signal to the after-heater (water or electric coil) in the supply air, 0-100 %."),
  _r("air_flap", "Air flap open", "holding", 100, "off", kind="bool", **DIAG,
     desc="Air flap (closing damper) output. ON = open while the unit runs."),
  _r("bypass_open", "Bypass opening", "holding", 102, kind="bool", icon="mdi:valve-open",
     desc="ON while the bypass damper motor is driven open. With the bypass open, fresh air goes around the heat "
          "exchanger (free cooling in summer)."),
  _r("bypass_close", "Bypass closing", "holding", 103, kind="bool", icon="mdi:valve-closed",
     desc="ON while the bypass damper motor is driven closed (all air through the heat exchanger)."),
  _r("heating_allowed", "After-heating allowed", "holding", 105, kind="bool", icon="mdi:radiator",
     desc="ON when the controller allows the after-heater (winter)."),
  _r("user_function_output", "User function active (output)", "holding", 123, kind="bool",
     icon="mdi:gesture-tap-button", desc="ON while a user function (1) runs."),
  _r("defrosting", "Defrosting", "holding", 125, kind="bool", icon="mdi:snowflake-melt",
     desc="ON while the heat exchanger is being de-iced (in frost the supply fan slows down or stops for a while)."),
  _r("alarm_relay", "Alarm relay output", "holding", 126, "off", kind="bool", **DIAG,
     desc="Alarm relay output. Reads ON on our unit without an alarm (fail-safe relay), so it is off by default."),

  # ---- clock ----
  _r("clock", "Nilan clock", "holding", 300, kind="clock", count=6, icon="mdi:clock-outline", **DIAG,
     desc="Date and time of the controller's own clock (HR 300-305). The Nilan week programs and the alarm log use "
          "it. 'Sync clock' on the page sets it to the Pi's time (the Pi gets its time from the internet)."),

  # ---- settings Home Assistant may change ----
  _r("run", "Run", "holding", 1001, "write", kind="bool", writable=True, icon="mdi:power",
     desc="Main on/off, same as the ON/OFF keys on the panel. OFF stops the unit, but a user function can still "
          "start it. Values: ON / OFF."),
  _r("mode", "Operating mode", "holding", 1002, "write", kind="enum", options=MODES, writable=True, icon="mdi:cog",
     desc="Off = no heating or cooling (ventilation only), Heat = after-heating allowed but no cooling, Cool = "
          "cooling allowed but no heating, Auto = the unit chooses (normal setting)."),
  _r("ventilation_step", "Ventilation step", "holding", 1003, "write", kind="enum", options=STEPS, writable=True,
     icon="mdi:fan", desc="User ventilation step, same as the step on the panel. " + STEP_TEXT +
     " A Nilan week program, the humidity control or a user function can change it again."),
  _r("temp_setpoint", "Room temperature setpoint", "holding", 1004, "write", **dict(T, state_class=None),
     writable=True, min=15, max=28, step=0.5, icon="mdi:thermostat",
     desc="Wanted room temperature. The unit heats the supply air (after-heater, inside the supply limits) when the "
          "room/extract temperature is below it, and opens the bypass / cools when above it (Cool/Auto). "
          "Allowed here 15-28 °C (spec 5-30)."),
  _r("alarm_reset", "Reset alarms", "holding", 400, "write", kind="button", press=255, writable=True,
     icon="mdi:alarm-off", category="config",
     desc="Clears all alarms (writes 255). Fix the cause first, otherwise the alarm comes back."),
  _r("weekly_program", "Week program", "holding", 500, "write", kind="enum", options=WEEK_PROGRAMS, writable=True,
     icon="mdi:calendar-week",
     desc="Which of the controller's own week programs runs: No program, Program 1, Program 2 or Program 3. Programs 1 "
          "and 2 are Nilan's presets, program 3 is the user program set up on the panel; the times and steps inside "
          "them can't be read or changed over Modbus on this controller. For a schedule you can see and edit, use "
          "the schedule on this page (and set this to No program). 'Erase' (4) is deliberately not offered."),

  _r("user_function_1", "User function 1 active", "holding", 600, "read", kind="bool", writable=True,
     icon="mdi:gesture-tap-button",
     desc="Starts/stops user function 1 like the panel key or the wired input: it runs what 'User function 1' is "
          "set to (e.g. Extended = boost ventilation) for 'User function 1 time'. Read only by default; set to "
          "write on the page to use it as a boost switch."),
  _r("user_function_1_mode", "User function 1", "holding", 601, "write", kind="enum", options=USER_FUNCTIONS, **CONF,
     desc="What user function 1 does: Not used; Extended = run at 'ventilation step' + 'temperature' for the set time "
          "(boost / party); Supply air = supply fan only; Extract air = extract fan only; External offset = shift "
          "the room setpoint by 'offset'; Ventilate = ventilation at the set step."),
  _r("user_function_1_time", "User function 1 time", "holding", 602, "write", kind="number", scale=1, unit="min",
     min=0, max=480, step=15, **CONF,
     desc="How long user function 1 runs after activation, 15-480 min (0 = as long as the input is active)."),
  _r("user_function_1_step", "User function 1 ventilation step", "holding", 603, "write", kind="enum",
     options=STEPS, **CONF, desc="Ventilation step while user function 1 runs. " + STEP_TEXT),
  _r("user_function_1_temp", "User function 1 temperature", "holding", 604, "write", kind="number", scale=1,
     unit="°C", device_class="temperature", min=5, max=30, step=1, **CONF,
     desc="Room setpoint while user function 1 runs (Extended only), 5-30 °C (whole degrees on this controller)."),
  _r("user_function_1_offset", "User function 1 offset", "holding", 605, "write", kind="number", scale=1,
     unit="°C", min=-10, max=10, step=1, **CONF,
     desc="Setpoint shift while user function 1 runs (External offset only), -10..+10 °C."),
  _r("user_function_2", "User function 2 active", "holding", 610, "read", kind="bool", writable=True,
     icon="mdi:gesture-tap-button", desc="Starts/stops user function 2 (see user function 1)."),
  _r("user_function_2_mode", "User function 2", "holding", 611, "write", kind="enum",
     options={**USER_FUNCTIONS, 6: "Cooker hood"}, **CONF,
     desc="What user function 2 does; like user function 1, plus Cooker hood = more extract/supply while the "
          "cooker hood contact is on."),
  _r("user_function_2_time", "User function 2 time", "holding", 612, "write", kind="number", scale=1, unit="min",
     min=0, max=480, step=15, **CONF, desc="How long user function 2 runs, 15-480 min (0 = while the input is on)."),
  _r("user_function_2_step", "User function 2 ventilation step", "holding", 613, "write", kind="enum",
     options=STEPS, **CONF, desc="Ventilation step while user function 2 runs. " + STEP_TEXT),
  _r("user_function_2_temp", "User function 2 temperature", "holding", 614, "write", kind="number", scale=1,
     unit="°C", device_class="temperature", min=5, max=30, step=1, **CONF,
     desc="Room setpoint while user function 2 runs (Extended only), 5-30 °C."),
  _r("user_function_2_offset", "User function 2 offset", "holding", 615, "write", kind="number", scale=1,
     unit="°C", min=-10, max=10, step=1, **CONF,
     desc="Setpoint shift while user function 2 runs (External offset only), -10..+10 °C."),

  _r("air_exchange_mode", "Air exchange mode", "holding", 1100, "read", kind="enum", options=AIR_EXCHANGE, **CONF,
     desc="Installer setting: Energy = lowest energy use, Comfort = more stable supply temperature, Comfort water = "
          "Comfort with a water after-heater."),
  _r("cooling_step", "Cooling ventilation step", "holding", 1101, "read", kind="enum",
     options={0: "No change", 1: "1", 2: "2", 3: "3", 4: "4"}, **CONF,
     desc="Ventilation step used while cooling (bypass free cooling in summer); 'No change' keeps the user step."),
  _r("cooling_offset", "Cooling setpoint offset", "holding", 1200, "read", kind="enum", options=COOL_OFFSET, **CONF,
     desc="Cooling starts when the room is this much above the room setpoint. 'Cooling off' = never cool/bypass for "
          "cooling. The Comfort 300 cools with its bypass (no compressor)."),
  _r("supply_min_summer", "Min supply air temperature summer", "holding", 1201, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF,
     desc="Lowest supply air temperature (T7) allowed in summer mode. Protects against cold draught when cooling."),
  _r("supply_min_winter", "Min supply air temperature winter", "holding", 1202, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF,
     desc="Lowest supply air temperature in winter mode; the after-heater keeps T7 at least here."),
  _r("supply_max_summer", "Max supply air temperature summer", "holding", 1203, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF,
     desc="Highest supply air temperature allowed in summer mode."),
  _r("supply_max_winter", "Max supply air temperature winter", "holding", 1204, "write",
     **dict(T, state_class=None), min=5, max=50, step=0.5, **CONF,
     desc="Highest supply air temperature in winter mode (limits how hot the after-heater makes the supply air)."),
  _r("summer_changeover", "Summer changeover temperature", "holding", 1205, "write",
     **dict(T, state_class=None), min=5, max=30, step=0.5, **CONF,
     desc="Outdoor temperature (T8, averaged) above which the unit switches to summer mode, below it winter mode."),
  _r("heat_extern_offset", "External heating offset", "holding", 1800, "off", **dict(T, state_class=None, **DIAG),
     desc="Offset from the room setpoint for an external heat source (e.g. radiators) controlled by the unit."),
  _r("humidity_low_step", "Low humidity ventilation step", "holding", 1910, "write", kind="enum", options=STEPS,
     **CONF, desc="Ventilation step in winter when the humidity is low (below the humidity limit), to avoid drying "
                  "out the house. " + STEP_TEXT),
  _r("humidity_high_step", "High humidity ventilation step", "holding", 1911, "write", kind="enum",
     options={0: "0", 2: "2", 3: "3", 4: "4"}, **CONF,
     desc="Ventilation step when the humidity rises quickly (shower, cooking). 0 = humidity control off."),
  _r("humidity_limit", "Humidity limit", "holding", 1912, "write", **dict(PCT, state_class=None), min=15, max=45,
     step=1, **CONF, desc="Below this relative humidity the unit uses the low humidity step (15-45 %)."),
  _r("humidity_max_time", "High humidity max time", "holding", 1913, "write", kind="number", scale=1, unit="min",
     min=0, max=180, step=1, **CONF,
     desc="Longest time on the high humidity step, 1-180 min (0 = no limit on this controller)."),
  _r("co2_high_step", "CO2 high ventilation step", "holding", 1920, "off", kind="enum",
     options={0: "0", 2: "2", 3: "3", 4: "4"}, **CONF, desc="Step when CO2 is high. Needs a CO2 sensor (not fitted)."),
  _r("co2_low_limit", "CO2 low limit", "holding", 1921, "off", kind="number", scale=1, unit="ppm", min=400, max=750,
     step=10, **CONF, desc="CO2 level for normal ventilation. Needs a CO2 sensor."),
  _r("co2_high_limit", "CO2 high limit", "holding", 1922, "off", kind="number", scale=1, unit="ppm", min=650,
     max=2500, step=10, **CONF, desc="CO2 level for high ventilation. Needs a CO2 sensor."),
  _r("service_mode", "Service mode", "holding", 1005, "off", kind="number", scale=1, **DIAG,
     desc="Installer test mode (0 = off). Never written by this program."),
  _r("service_capacity", "Service capacity", "holding", 1006, "off", **dict(PCT, **DIAG),
     desc="Output used in service mode. Never written by this program."),
]

KINDS = ("number", "enum", "bool", "text", "button", "clock")

# The CTS 602 only reports the step the user chose (HR 1003); its humidity control and user functions run the fans higher
# without changing it, and the "actual step" registers (IR 1100-1102) do not answer on our unit. So the step the unit
# really runs is worked out from the extract fan speed. Limits = halfway between the steps measured on our Comfort 300
# on 2026-10-01 (extract fan 27 / 46 / 64 / 100 % at steps 1 / 2 / 3 / 4); the installer sets these speeds per unit.
STEP_FAN_LIMITS = (36.5, 55.0, 82.0)


def actual_step(extract_fan_pct):
  """Extract fan speed in % -> ventilation step 0-4 (None when the speed is unknown)"""
  if not isinstance(extract_fan_pct, (int, float)):
    return None
  if extract_fan_pct < 1:
    return 0
  return 1 + sum(extract_fan_pct >= limit for limit in STEP_FAN_LIMITS)
KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def decimals(scale):
  """0.01 -> 2, 0.1 -> 1, 1 -> 0"""
  text = f"{scale:.10f}".rstrip("0")
  return len(text.split(".")[1]) if "." in text else 0


def span(r):
  return r.get("count", 1) if r["kind"] in ("text", "clock") else 1


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
  if kind == "clock":
    s, mi, h, d, mo, y = words[:6]
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
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


def clock_words(t):
  """time.struct_time -> the 6 clock registers (second, minute, hour, day, month, year)"""
  return [t.tm_sec, t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon, t.tm_year]


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


def range_text(r):
  """'15 … 28 °C, step 0.5' / 'Off, Heat, Cool, Auto' / 'ON / OFF' for the page and HA"""
  if r["kind"] == "enum":
    return ", ".join(r["options"].values())
  if r["kind"] == "bool":
    return "ON / OFF"
  if r["kind"] == "button":
    return "press"
  if r["kind"] == "number" and "min" in r:
    return f"{r['min']} … {r['max']} {r.get('unit', '')}".rstrip() + f", step {r.get('step') or r.get('scale', 1)}"
  return ""
