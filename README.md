# nilan_mqtt

Reads and controls a **Nilan Comfort 300 ventilation unit (CTS 602 controller)** over **Modbus RTU** (RS485 USB adapter)
and connects it to **Home Assistant through MQTT**. A password-protected HTTPS web page sets everything up.

Version 1.0 (2026-09-30) is a rewrite (1.1: descriptions, versions, diagram, week schedule, clock); the old Flask/pymodbus version is in the git history (commits before 1.0).
Sister programs on the same Raspberry Pi: [kamstrup2mqtt](https://github.com/laithsaid/kamstrup2mqtt) (heat meter, :8080)
and flowiq2mqtt (water meter, :8081).

## Parts
| File | What |
|---|---|
| `modbus_rtu.py` | Modbus RTU master (pyserial only): functions 03/04 read, 16 write, CRC, retries, reopens an unplugged adapter |
| `registers.py` | The CTS 602 register table (what exists on a Comfort 300, scaling, options, limits, which are writable) |
| `poller.py` | The only thread that talks Modbus: reads every *interval*, does the writes, publishes, HA discovery |
| `bridge.py` | MQTT client (paho): connects with the page's settings, receives commands from HA |
| `ha.py` | Home Assistant discovery: sensor / binary_sensor for read, number / select / switch / button for write |
| `webserver.py`, `web/` | The page: values (+ change them), Modbus settings + connection test, MQTT settings, register table, log |
| `settings.py` | Settings from the page, checked and saved in `settings.json` (mode 600, has the MQTT password) |
| `schedule.py` | The week schedule run by this program (see below) |
| `sim.py` | A fake Nilan (serial port `simulate`) for testing without hardware |

## Rules for writing
- A register is read only if its access on the page is **read** or **write**; **off** = not read and not in HA.
- Only access **write** can be written, from Home Assistant or the page. Built-in registers can be set to write only when
  the Nilan spec allows it (holding registers); custom holding registers need a min and max.
- Numbers must be inside min..max (you can narrow the spec limits on the page), choices must be one of the options.
- Every write is read back; if the unit kept another value, that is logged and shown.
- A value the register already has is not written again; at most 20 writes per minute.

Writable by default: run, operating mode, ventilation step, room temperature setpoint (15–28 °C), alarm reset,
user functions 1/2 (mode, time, step, temperature, offset), min/max supply air temperatures, summer changeover,
humidity steps / limit / max time. Available but read only by default: user function "active", air exchange mode,
cooling step/offset. Not writable at all: service mode, outputs, device type.

## The page
- Header: Nilan device type, controller software version, Modbus bus version, program version.
- **The unit**: the Comfort 300 LR (right model, ducts on both ends) as in Nilan's function diagram (filters, T8/T3/T4/T7, heat exchanger, fans, after-heater,
  bypass, panel) with the live values.
- **Values**: every enabled register; **i** opens what it is, the register number, the allowed values and what each
  option does. Writable ones have a Set control.
- **Week schedule** and **Clock** (below), Modbus and MQTT settings, the register table (also with descriptions), the log.

## Week schedule
The CTS 602 (bus version 5) only lets you *choose* its own week program over Modbus (register 500: None, Program 1-3);
the times inside those programs can't be read or changed. So this program has its own schedule: periods with weekdays,
a start time, a ventilation step and/or a room setpoint. A period is applied once when it starts; changes from the
panel, the page or HA stay until the next period. Saving applies the current period at once; after a restart the
current period is not applied again. Turn the Nilan's own program to None when using it (the page warns).
HA: `switch.nilan_schedule`, `sensor.nilan_schedule_next`.

## Clock
The Nilan's clock (HR 300-305) is shown next to the Pi's; "Set Nilan clock" (page) or `button.nilan_sync_clock` (HA)
sets it to the Pi's time at the next full minute (the controller ignores the seconds); optional automatic sync when it is more than 1 minute off (at most every 6 h).

## MQTT (topic `nilan/CTS602` by default)
- `nilan/CTS602/state`: JSON with all values (retained)
- `nilan/CTS602/status`: `online` / `read error` (the unit stops answering; retained)
- `nilan/CTS602/lwt`: `online` / `offline` (the program)
- `nilan/CTS602/set/<key>`: commands, e.g. `set/temp_setpoint` = `21.5`, `set/mode` = `Auto`, `set/run` = `OFF`
- `nilan/CTS602/attributes/<key>`: description, register and allowed values (shown as attributes in HA)
- `homeassistant/<component>/nilan_cts602/<key>/config`: discovery; entities `sensor.nilan_<key>`, `number.nilan_<key>`, ...

## Install on the Pi
```
# from the PC
scp -r nilan_mqtt laith@192.168.1.121:/home/laith/
# on the Pi (paho-mqtt and pyserial are already there for the other readers)
cd ~/nilan_mqtt
python3 web_password.py                       # web login (or copy another reader's web_auth.json)
# HTTPS: set WEB_TLS_CERT / WEB_TLS_KEY in config.py to the heat reader's certificate, or: sh tools/make_web_cert.sh
sudo cp systemd/nilan-mqtt.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now nilan-mqtt
```
Then open https://192.168.1.121:8082/, set the serial port (`/dev/serial/by-id/usb-FTDI_...`) and the MQTT broker + login,
press **Save**, then **Test connection**. The Nilan CTS 602 defaults: 19200 baud, 8E1, unit 30.

## Tests
`python -m unittest discover -s tests` (uses the fake Nilan; no hardware or broker needed).
