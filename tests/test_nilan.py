"""python -m unittest discover -s tests   (from the program folder)"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ha                      # noqa: E402
import modbus_rtu              # noqa: E402
import poller as poller_mod    # noqa: E402
import registers as R          # noqa: E402
import settings as S           # noqa: E402
import sim                     # noqa: E402


def master(fake=None):
  fake = fake or sim.FakeNilan()
  return modbus_rtu.RtuMaster("fake", timeout=0.1, retries=1, gap_s=0, serial_factory=lambda **kw: fake), fake


class TestModbus(unittest.TestCase):
  def test_crc(self):
    # well-known example frame: 01 03 00 00 00 0A -> CRC C5 CD
    self.assertEqual(modbus_rtu.crc16(bytes.fromhex("01030000000A")), bytes.fromhex("C5CD"))

  def test_read_and_write(self):
    m, fake = master()
    self.assertEqual(m.read(30, "input", 200, 4), [2774, 0, 0, 2188])
    self.assertEqual(m.read(30, "holding", 1004, 1), [2200])
    m.write(30, 1004, [2150])
    self.assertEqual(m.read(30, "holding", 1004, 1), [2150])
    self.assertEqual(fake.writes, [(1004, 2150)])

  def test_exception(self):
    m, _ = master()
    with self.assertRaises(modbus_rtu.ModbusException) as cm:
      m.read(30, "holding", 1102, 1)
    self.assertEqual(cm.exception.code, 2)

  def test_timeout_and_wrong_unit(self):
    m, fake = master()
    fake.silent = True
    with self.assertRaises(modbus_rtu.ModbusError) as cm:
      m.read(30, "input", 200, 1)
    self.assertNotIsInstance(cm.exception, modbus_rtu.ModbusException)
    fake.silent = False
    with self.assertRaises(modbus_rtu.ModbusError):
      m.read(31, "input", 200, 1)       # nobody answers unit 31

  def test_no_port(self):
    m = modbus_rtu.RtuMaster("")
    with self.assertRaises(modbus_rtu.ModbusError):
      m.read(30, "input", 0, 1)


class TestRegisters(unittest.TestCase):
  def setUp(self):
    self.r = R.by_key()

  def test_decode(self):
    self.assertEqual(R.decode(self.r["t3_exhaust"], [2188]), 21.88)
    self.assertEqual(R.decode(self.r["t8_outdoor"], [65536 - 350]), -3.5)
    self.assertEqual(R.decode(self.r["time_in_state"], [55103]), 55103)
    self.assertEqual(R.decode(self.r["mode"], [3]), "Auto")
    self.assertEqual(R.decode(self.r["alarm_1"], [19]), "E19 Change air filter")
    self.assertEqual(R.decode(self.r["alarm_1"], [99]), "Unknown (99)")
    self.assertEqual(R.decode(self.r["run"], [1]), "ON")
    self.assertEqual(R.decode(self.r["alarm_count"], [0x8002]), 2)
    self.assertEqual(R.decode(self.r["display_line_1"], [21825, 20308, 8224, 12576]), "AUTO   1")
    self.assertEqual(R.decode(self.r["display_line_2"], [12606, 8252, 12850, 17375]), ">1< 22°C")
    self.assertEqual(R.decode(self.r["software_version"], [11826, 12594, 30720]), "2.21")

  def test_encode(self):
    self.assertEqual(R.encode(self.r["temp_setpoint"], "21.5"), 2150)
    self.assertEqual(R.encode(self.r["mode"], "Heat"), 1)
    self.assertEqual(R.encode(self.r["mode"], "2"), 2)
    self.assertEqual(R.encode(self.r["run"], "OFF"), 0)
    self.assertEqual(R.encode(self.r["user_function_1_offset"], "-3"), 65533)
    self.assertEqual(R.encode(self.r["alarm_reset"], "PRESS"), 255)
    for key, bad in (("temp_setpoint", "35"), ("temp_setpoint", "nan"), ("temp_setpoint", "x"), ("mode", "Turbo"),
                     ("run", "maybe"), ("ventilation_step", "5"), ("humidity_high_step", "1")):
      with self.assertRaises(ValueError, msg=f"{key}={bad}"):
        R.encode(self.r[key], bad)

  def test_table_consistent(self):
    keys = [r["key"] for r in R.BUILTIN]
    self.assertEqual(len(keys), len(set(keys)))
    seen = set()
    for r in R.BUILTIN:
      self.assertIn(r["kind"], R.KINDS)
      self.assertTrue(R.KEY_RE.match(r["key"]))
      self.assertNotIn((r["table"], r["address"]), seen, r["key"])
      seen.add((r["table"], r["address"]))
      if r.get("writable"):
        self.assertEqual(r["table"], "holding", r["key"])
        if r["kind"] == "number":
          self.assertLess(r["min"], r["max"])
      if r["access"] == "write":
        self.assertTrue(r.get("writable"), r["key"])
      if r["access"] != "off" and r["kind"] != "button":
        # every register switched on by default answers on our unit (values from 2026-09-30)
        self.assertIn(r["address"], sim.INPUT if r["table"] == "input" else sim.HOLDING, r["key"])


class TestSettings(unittest.TestCase):
  def test_defaults(self):
    s = S.validate(S.defaults())
    self.assertEqual(s["modbus"]["unit"], 30)
    self.assertEqual(s["interval_s"], 30)

  def test_access(self):
    s = S.defaults()
    s["registers"] = {"t3_exhaust": {"access": "write"}}
    with self.assertRaises(ValueError):
      S.validate(s)
    s["registers"] = {"user_function_1": {"access": "write"}, "t3_exhaust": {"access": "off"}, "gone": {"access": "read"}}
    out = S.validate(s)
    self.assertEqual(out["registers"], {"user_function_1": {"access": "write"}, "t3_exhaust": {"access": "off"}})
    table = {r["key"]: r for r in S.effective(out)}
    self.assertEqual(table["t3_exhaust"]["access"], "off")

  def test_limits_inside_spec(self):
    s = S.defaults()
    s["registers"] = {"temp_setpoint": {"access": "write", "min": 18, "max": 24}}
    out = S.validate(s)
    self.assertEqual(S.effective(out)[[r["key"] for r in S.effective(out)].index("temp_setpoint")]["max"], 24)
    s["registers"] = {"temp_setpoint": {"access": "write", "min": 10, "max": 24}}
    with self.assertRaises(ValueError):
      S.validate(s)

  def test_custom(self):
    s = S.defaults()
    s["custom"] = [{"key": "hr_1101", "name": "x", "table": "holding", "address": 1101, "kind": "number", "scale": 1,
                    "access": "write"}]
    with self.assertRaises(ValueError):          # writable number needs min/max
      S.validate(s)
    s["custom"][0].update(min=0, max=4)
    out = S.validate(s)
    self.assertTrue([r for r in S.effective(out) if r["key"] == "hr_1101"][0]["writable"])
    s["custom"][0]["key"] = "t3_exhaust"
    with self.assertRaises(ValueError):
      S.validate(s)
    s["custom"] = [{"key": "ir", "table": "input", "address": 5, "access": "write", "min": 0, "max": 1}]
    with self.assertRaises(ValueError):
      S.validate(s)

  def test_password_kept_and_hidden(self):
    old = S.validate(dict(S.defaults(), mqtt=dict(S.defaults()["mqtt"], host="10.0.0.1", password="pw")))
    new = S.validate(dict(old, mqtt=dict(old["mqtt"], password="")), old)
    self.assertEqual(new["mqtt"]["password"], "pw")
    self.assertNotIn("password", S.public(new)["mqtt"])
    self.assertTrue(S.public(new)["mqtt"]["password_set"])
    self.assertIn("mqtt.password changed", S.describe_changes(old, dict(new, mqtt=dict(new["mqtt"], password="x"))))

  def test_bad_values(self):
    for change in ({"modbus": {"port": "COM3; rm"}}, {"modbus": {"parity": "X"}}, {"interval_s": 1},
                   {"mqtt": {"topic": "a/+/b"}}, {"mqtt": {"host": "a b"}}):
      with self.assertRaises(ValueError, msg=str(change)):
        S.validate(dict(S.defaults(), **change))


class FakeBridge:
  def __init__(self, on_command, on_connected):
    self.on_command, self.on_connected = on_command, on_connected
    self.connected = True
    self.msgs = []
    self.retained = {}

  def apply(self, cfg):
    self.cfg = cfg

  def publish(self, topic, payload, retain=False, qos=1):
    self.msgs.append((topic, payload))
    if retain:
      self.retained[topic] = payload
    return True

  def status(self):
    return {"connected": True}

  def stop(self):
    pass


class TestPoller(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp()
    poller_mod.ANNOUNCED_FILE = os.path.join(self.dir, "announced.json")
    s = S.defaults()
    s["modbus"]["port"] = "simulate"
    s["mqtt"]["host"] = "broker"
    with open(os.path.join(self.dir, "settings.json"), "w") as f:
      json.dump(s, f)
    self.settings = S.Settings(os.path.join(self.dir, "settings.json"))
    self.p = poller_mod.Poller(self.settings, FakeBridge, "test")
    self.p.master.gap_s = 0
    self.p._read(self.settings.get())

  def state(self):
    return json.loads(self.p.bridge.retained["nilan/CTS602/state"])

  def test_blocks(self):
    blocks = poller_mod.Poller.blocks(self.p.table())
    starts = [(b[0], b[1], b[2]) for b in blocks]
    self.assertIn(("input", 203, 2), starts)          # T3 + T4 in one request
    self.assertIn(("input", 1000, 4), starts)
    self.assertTrue(all(b[2] <= poller_mod.MAX_BLOCK for b in blocks))

  def test_read(self):
    v = self.state()
    self.assertEqual(v["t3_exhaust"], 21.88)
    self.assertEqual(v["mode"], "Auto")
    self.assertEqual(v["ventilation_step"], "1")
    self.assertEqual(v["display_line_1"], "AUTO   1")
    self.assertEqual(v["exhaust_fan"], 100)
    self.assertNotIn("t1_intake", v)                  # off by default
    self.assertEqual(self.p.bridge.retained["nilan/CTS602/status"], "online")
    self.assertEqual(self.p.errors, {})

  def test_missing_register_does_not_break_the_read(self):
    del self.p.fake.input[1204]
    self.p._read(self.settings.get())
    self.assertIn("exchanger_efficiency", self.p.errors)
    self.assertEqual(self.state()["t3_exhaust"], 21.88)
    self.assertEqual(self.p.fails, 0)

  def test_unit_silent(self):
    self.p.fake.silent = True
    self.p._read(self.settings.get())
    self.p._read(self.settings.get())
    self.assertEqual(self.p.bridge.retained["nilan/CTS602/status"], "read error")
    self.p.fake.silent = False
    self.p._read(self.settings.get())
    self.assertEqual(self.p.bridge.retained["nilan/CTS602/status"], "online")

  def job(self, key, value):
    req = poller_mod.WriteRequest(key, value, "test")
    self.p._job(self.settings.get(), req)
    return req.result

  def test_write(self):
    self.assertEqual(self.job("temp_setpoint", "21.5"), {"ok": True, "value": 21.5})
    self.assertEqual(self.p.fake.holding[1004], 2150)
    self.assertEqual(self.state()["temp_setpoint"], 21.5)
    self.assertEqual(self.job("ventilation_step", "3")["value"], "3")
    self.assertEqual(self.job("mode", "Heat")["value"], "Heat")
    self.assertEqual(self.job("run", "OFF")["value"], "OFF")
    self.assertEqual(self.p.fake.holding[1001], 0)

  def test_write_refused(self):
    writes = len(self.p.fake.writes)
    self.assertFalse(self.job("t3_exhaust", "20")["ok"])            # input register
    self.assertFalse(self.job("user_function_1", "ON")["ok"])       # writable, but access is read
    self.assertFalse(self.job("service_mode", "1")["ok"])           # not writable at all
    self.assertFalse(self.job("nope", "1")["ok"])
    self.assertFalse(self.job("temp_setpoint", "40")["ok"])         # outside min..max
    self.assertEqual(len(self.p.fake.writes), writes)
    self.assertEqual(self.p.st["writes_failed"], 5)

  def test_write_same_value_not_sent(self):
    r = self.job("temp_setpoint", "22")
    self.assertEqual(r["note"], "already set")
    self.assertEqual(self.p.fake.writes, [])

  def test_rate_limit(self):
    for i in range(poller_mod.MAX_WRITES_PER_MIN):
      self.assertTrue(self.job("temp_setpoint", str(16 + (i % 2)))["ok"])
    self.assertIn("writes in a minute", self.job("temp_setpoint", "20")["error"])

  def test_unit_keeps_other_value(self):
    orig = self.p.fake.write
    def clamp(frame):
      orig(frame)
      if frame[1] == 16:
        self.p.fake.holding[1004] = 2400
    self.p.fake.write = clamp
    r = self.job("temp_setpoint", "25")
    self.assertFalse(r["ok"])
    self.assertEqual(r["value"], 24.0)

  def test_button(self):
    self.assertTrue(self.job("alarm_reset", "PRESS")["ok"])
    self.assertEqual(self.p.fake.writes[-1], (400, 255))

  def test_discovery_and_removal(self):
    self.p._announce(self.settings.get())
    ret = self.p.bridge.retained
    number = json.loads(ret["homeassistant/number/nilan_cts602/temp_setpoint/config"])
    self.assertEqual((number["min"], number["max"], number["command_topic"]), (15, 28, "nilan/CTS602/set/temp_setpoint"))
    select = json.loads(ret["homeassistant/select/nilan_cts602/mode/config"])
    self.assertEqual(select["options"], ["Off", "Heat", "Cool", "Auto"])
    self.assertIn("homeassistant/switch/nilan_cts602/run/config", ret)
    self.assertIn("homeassistant/button/nilan_cts602/alarm_reset/config", ret)
    sensor = json.loads(ret["homeassistant/sensor/nilan_cts602/t3_exhaust/config"])
    self.assertEqual(sensor["default_entity_id"], "sensor.nilan_t3_exhaust")
    self.assertNotIn("entity_category", json.loads(ret["homeassistant/sensor/nilan_cts602/air_exchange_mode/config"]))
    # switch the setpoint to read and T3 off: number -> sensor, T3 config removed
    s = self.settings.get()
    s["registers"] = {"temp_setpoint": {"access": "read"}, "t3_exhaust": {"access": "off"}}
    self.settings.update(s)
    self.p._announce(self.settings.get())
    self.assertEqual(ret["homeassistant/number/nilan_cts602/temp_setpoint/config"], "")
    self.assertIn("homeassistant/sensor/nilan_cts602/temp_setpoint/config", ret)
    self.assertEqual(ret["homeassistant/sensor/nilan_cts602/t3_exhaust/config"], "")
    self.assertNotIn("t3_exhaust", self.p.values)

  def test_mqtt_command_goes_through_queue(self):
    self.p.bridge.on_command("ventilation_step", "2")
    req = self.p.jobs.get_nowait()
    self.p._job(self.settings.get(), req)
    self.assertEqual(self.p.fake.holding[1003], 2)
    self.assertEqual(self.p.st["last_write"]["source"], "Home Assistant")


if __name__ == "__main__":
  unittest.main()
