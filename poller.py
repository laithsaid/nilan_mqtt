"""
The worker thread: the only thread that talks Modbus. Reads the enabled registers every interval_s, does the writes
asked for by Home Assistant (MQTT), the page or the schedule, publishes the values and the Home Assistant discovery.

MQTT (topic from the page, default nilan/CTS602):
  <topic>/state        JSON {key: value, ..., "timestamp": unix s} after every read and write (retained)
  <topic>/status       "online" after a good read, "read error" after FAILS_BEFORE_UNAVAILABLE failed reads (retained)
  <topic>/lwt          program online / offline (bridge.py)
  <topic>/set/<key>    commands; only registers with access "write", only values inside min..max / the options;
                       plus set/schedule (ON/OFF) and set/sync_clock (PRESS)
  <topic>/attributes/<key>   description, register and range of each entity (retained, HA shows them as attributes)
  <prefix>/<component>/<node>/<key>/config   discovery (retained); removed again when a register is switched off

Writes are checked by reading the register back. At most MAX_WRITES_PER_MIN writes per minute (protects the unit's
settings memory from a runaway automation); a write of the value the register already has is not sent.
"""

import datetime
import json
import os
import queue
import threading
import time

import ha
import logs
import modbus_rtu
import registers as regs_mod
import schedule as sched
import settings as settings_mod
import sim

logger = logs.get("poller")

FAILS_BEFORE_UNAVAILABLE = 2
MAX_BLOCK = 30                  # registers per read request
MAX_WRITES_PER_MIN = 20
CLOCK_SYNC_LIMIT_S = 60         # automatic clock sync when the Nilan's clock is off by more than this
CLOCK_SYNC_EVERY_S = 6 * 3600   # ... at most this often
ANNOUNCED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "announced.json")
SCHEDULE_STATE_FILE = sched.STATE_FILE


class WriteRequest:
  def __init__(self, key, value, source):
    self.key, self.value, self.source = key, value, source
    self.done = threading.Event()
    self.result = None


class Poller(threading.Thread):
  def __init__(self, settings, bridge_factory, version=""):
    super().__init__(name="poller", daemon=True)
    self.settings = settings
    self.version = version
    self.stopper = threading.Event()
    self.wake = threading.Event()
    self.jobs = queue.Queue()
    self.lock = threading.Lock()
    self.fake = None
    self.master = modbus_rtu.RtuMaster(serial_factory=self._serial_factory)
    self.bridge = bridge_factory(self.command_from_mqtt, self._mqtt_connected)
    self.announce_wanted = threading.Event()
    self.read_wanted = False
    self.write_times = []
    self.fails = 0
    self.values = {}                # key -> decoded value (last known)
    self.raw = {}                   # key -> raw words
    self.errors = {}                # key -> last error for that register
    self.clock_drift = None         # Nilan clock minus Pi clock, seconds
    self.last_clock_sync = 0
    self.schedule_applied = sched.load_state(SCHEDULE_STATE_FILE)
    self.st = {"last_read": None, "last_ok": None, "last_error": None, "reads_ok": 0, "reads_failed": 0,
               "read_duration_s": None, "writes_ok": 0, "writes_failed": 0, "last_write": None, "test": None,
               "last_schedule": None}
    self._apply(None, settings.get())
    settings.on_change(self._apply)

  # ---- settings ----
  def _serial_factory(self, port, **kw):
    if port == "simulate":
      if self.fake is None:
        self.fake = sim.FakeNilan(unit=self.settings.get()["modbus"]["unit"])
      return self.fake
    return modbus_rtu.serial.Serial(port=port, **kw)

  def _apply(self, old, new):
    m = new["modbus"]
    if old is None or old["modbus"] != m:
      self.master.configure(m["port"], m["baudrate"], m["bytesize"], m["parity"], m["stopbits"], m["timeout"],
                            m["retries"], m["gap_ms"] / 1000)
    self.bridge.apply(new["mqtt"])
    if old is not None:
      with self.lock:
        # values of registers that are no longer read are dropped
        active = {r["key"] for r in settings_mod.effective(new) if r["access"] != "off"}
        for d in (self.values, self.raw, self.errors):
          for k in [k for k in d if k not in active]:
            del d[k]
      if old["schedule"] != new["schedule"]:
        self._set_schedule_applied(None)      # a changed schedule applies its current period straight away
      self.announce_wanted.set()
      self.read_wanted = True
      self.wake.set()

  def table(self, s=None):
    return settings_mod.effective(s or self.settings.get())

  # ---- called from other threads ----
  def command_from_mqtt(self, key, payload):
    self.jobs.put(WriteRequest(key, payload, "Home Assistant"))
    self.wake.set()

  def write(self, key, value, source, wait_s=10):
    """From the page: queue a write and wait for the result"""
    req = WriteRequest(key, value, source)
    self.jobs.put(req)
    self.wake.set()
    if not req.done.wait(wait_s):
      return {"ok": False, "error": "timeout: the write is still queued"}
    return req.result

  def request_read(self):
    self.read_wanted = True
    self.wake.set()

  def test(self, wait_s=15):
    """Read bus version + device type with the saved settings"""
    return self.write(None, None, "test", wait_s)

  def _mqtt_connected(self):
    self.announce_wanted.set()
    self.wake.set()

  def schedule_info(self, s=None):
    s = s or self.settings.get()
    now = datetime.datetime.now()
    periods = s["schedule"]["periods"]
    cur_start, cur = sched.current(periods, now)
    nxt_start, nxt = sched.upcoming(periods, now)
    return {"enabled": s["schedule"]["enabled"], "current": sched.label(cur_start, cur) if cur else None,
            "next": sched.label(nxt_start, nxt) if nxt else None, "applied": self.schedule_applied}

  def snapshot(self):
    with self.lock:
      return {"values": dict(self.values), "raw": dict(self.raw), "errors": dict(self.errors), "stats": dict(self.st),
              "mqtt": self.bridge.status(), "fails_in_a_row": self.fails, "clock_drift_s": self.clock_drift,
              "schedule": self.schedule_info(), "device": self.device_info()}

  def device_info(self):
    v = self.values
    return {"software": v.get("software_version"), "bus_version": v.get("bus_version"),
            "type": v.get("device_type"), "program": self.version}

  # ---- publishing ----
  def _extras(self, s):
    """Values that are not registers: schedule on/off + next change, clock drift"""
    info = self.schedule_info(s)
    out = {"schedule": "ON" if info["enabled"] else "OFF", "schedule_next": info["next"] or "none"}
    if self.clock_drift is not None:
      out["clock_drift"] = self.clock_drift
    return out

  def _publish_state(self, s):
    with self.lock:
      values = dict(self.values)
    if values:
      values.update(self._extras(s))
      values["timestamp"] = int(time.time())
      self.bridge.publish(s["mqtt"]["topic"] + "/state", json.dumps(values, ensure_ascii=False, sort_keys=True),
                          retain=True)

  def _load_announced(self):
    try:
      with open(ANNOUNCED_FILE, encoding="utf-8") as f:
        return set(json.load(f))
    except (OSError, ValueError, TypeError):
      return set()

  def _save_announced(self, topics):
    try:
      tmp = ANNOUNCED_FILE + ".tmp"
      with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(topics), f, indent=1)
      os.replace(tmp, ANNOUNCED_FILE)
    except OSError as e:
      logger.warning(f"could not save {ANNOUNCED_FILE}: {e}")

  def _announce(self, s):
    """Send discovery + descriptions for the enabled registers; remove what was announced before and is no longer
    wanted"""
    if not self.bridge.connected:
      return
    self.announce_wanted.clear()
    table = self.table(s)
    wanted = ha.configs(s["mqtt"], table, self.device_info()) if s["mqtt"]["discovery"] else {}
    attributes = ha.attributes(s["mqtt"], table) if s["mqtt"]["discovery"] else {}
    before = self._load_announced()
    for topic in before - set(wanted) - set(attributes):
      self.bridge.publish(topic, "", retain=True)
    for topic, payload in list(attributes.items()) + list(wanted.items()):
      self.bridge.publish(topic, payload, retain=True)
    now = set(wanted) | set(attributes)
    if before != now:
      self._save_announced(now)
    removed = len({t for t in before - now if t.endswith("/config")})
    logger.info(f"Home Assistant discovery: {len(wanted)} entities" + (f", {removed} removed" if removed else ""))
    self._publish_state(s)
    self.bridge.publish(s["mqtt"]["topic"] + "/status", "online" if self.fails < FAILS_BEFORE_UNAVAILABLE and
                        self.st["last_ok"] else "read error", retain=True)

  # ---- reading ----
  @staticmethod
  def blocks(table):
    """Group registers into contiguous read requests per table: [(table, start, count, [registers])]"""
    out = []
    for tbl in ("input", "holding"):
      regs = sorted((r for r in table if r["table"] == tbl and r["access"] != "off" and r["kind"] != "button"),
                    key=lambda r: r["address"])
      cur = None
      for r in regs:
        n = regs_mod.span(r)
        if cur and r["address"] == cur[1] + cur[2] and cur[2] + n <= MAX_BLOCK:
          cur[2] += n
          cur[3].append(r)
        else:
          cur = [tbl, r["address"], n, [r]]
          out.append(cur)
    return [tuple(b) for b in out]

  def _read_block(self, unit, tbl, start, count, regs, values, raw, errors):
    try:
      words = self.master.read(unit, tbl, start, count)
    except modbus_rtu.ModbusException as e:
      if len(regs) == 1:
        errors[regs[0]["key"]] = str(e)
        return
      # one register in the block is not there: read them one by one
      for r in regs:
        self._read_block(unit, tbl, r["address"], regs_mod.span(r), [r], values, raw, errors)
      return
    for r in regs:
      i = r["address"] - start
      w = words[i:i + regs_mod.span(r)]
      raw[r["key"]] = w
      values[r["key"]] = regs_mod.decode(r, w)

  def _clock_check(self, s, clock_text, read_at):
    try:
      nilan = datetime.datetime.strptime(clock_text, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
      self.clock_drift = None
      return
    self.clock_drift = int(round(nilan - read_at))
    if s["clock_sync"] and abs(self.clock_drift) > CLOCK_SYNC_LIMIT_S and \
       time.time() - self.last_clock_sync > CLOCK_SYNC_EVERY_S:
      logger.info(f"Nilan clock is {self.clock_drift:+d} s off: syncing it (automatic clock sync is on)")
      try:
        self._sync_clock(s, "automatic clock sync")
      except (modbus_rtu.ModbusError, ValueError) as e:
        logger.warning(f"automatic clock sync failed: {e}")

  def _read(self, s):
    t0 = time.time()
    self.st["last_read"] = t0
    values, raw, errors = {}, {}, {}
    try:
      for tbl, start, count, regs in self.blocks(self.table(s)):
        self._read_block(s["modbus"]["unit"], tbl, start, count, regs, values, raw, errors)
    except (modbus_rtu.ModbusError, ValueError) as e:
      self.fails += 1
      with self.lock:
        self.st["reads_failed"] += 1
        self.st["last_error"] = f"{time.strftime('%Y-%m-%d %H:%M:%S')} read: {e}"
      logger.warning(f"read failed ({self.fails} in a row): {e}")
      if self.fails >= FAILS_BEFORE_UNAVAILABLE:
        if self.fails == FAILS_BEFORE_UNAVAILABLE:
          logger.warning("the Nilan's entities are now unavailable in Home Assistant")
        self.bridge.publish(s["mqtt"]["topic"] + "/status", "read error", retain=True)
      return
    if self.fails >= FAILS_BEFORE_UNAVAILABLE:
      logger.info(f"the Nilan answers again after {self.fails} failed reads")
    self.fails = 0
    new_errors = {k: v for k, v in errors.items() if self.errors.get(k) != v}
    for k, v in new_errors.items():
      logger.warning(f"register {k}: {v} (switch it off on the page if the unit does not have it)")
    first = not self.st.get("versions_seen") and "software_version" in values
    with self.lock:
      self.values.update(values)
      self.raw.update(raw)
      self.errors = errors
      self.st.update(last_ok=time.time(), read_duration_s=round(time.time() - t0, 2))
      self.st["reads_ok"] += 1
    if first:
      self.st["versions_seen"] = True
      logger.info(f"Nilan {values.get('device_type', '?')}, software {values['software_version']}, "
                  f"Modbus bus version {values.get('bus_version', '?')}")
      self.announce_wanted.set()     # device info with the versions
    if "clock" in values:
      self._clock_check(s, values["clock"], t0)
    self._publish_state(s)
    self.bridge.publish(s["mqtt"]["topic"] + "/status", "online", retain=True)

  # ---- writing ----
  def _rate_limit(self):
    now = time.time()
    self.write_times = [t for t in self.write_times if now - t < 60]
    if len(self.write_times) >= MAX_WRITES_PER_MIN:
      raise ValueError(f"more than {MAX_WRITES_PER_MIN} writes in a minute; try again later")
    self.write_times.append(now)

  def _do_write(self, s, key, value, source):
    table = {r["key"]: r for r in self.table(s)}
    r = table.get(key)
    if r is None or r["access"] != "write":
      raise ValueError(f"{key} is not writable (not in the table, or its access is not 'write' on the page)")
    raw = regs_mod.encode(r, value)
    unit = s["modbus"]["unit"]
    if r["kind"] != "button":
      current = self.master.read(unit, "holding", r["address"], 1)[0]
      if current == raw:
        value = regs_mod.decode(r, [raw])
        with self.lock:
          self.values[r["key"]], self.raw[r["key"]] = value, [raw]
        return {"ok": True, "value": value, "note": "already set"}
    self._rate_limit()
    old = self.values.get(r["key"])
    self.master.write(unit, r["address"], [raw])
    if r["kind"] == "button":
      logger.info(f"write {r['key']} (pressed, {r['address']} = {raw}) by {source}")
      return {"ok": True}
    back = self.master.read(unit, "holding", r["address"], 1)[0]
    value = regs_mod.decode(r, [back])
    with self.lock:
      self.values[r["key"]], self.raw[r["key"]] = value, [back]
    if back != raw:
      logger.warning(f"write {r['key']}: sent {regs_mod.decode(r, [raw])}, the unit kept {value} (by {source})")
      return {"ok": False, "value": value, "error": f"the unit kept {value}"}
    logger.info(f"write {r['key']}: {old} -> {value} by {source}")
    return {"ok": True, "value": value}

  def _sync_clock(self, s, source):
    """Set the Nilan's clock (HR 300-305) to the Pi's local time and read it back"""
    self._rate_limit()
    unit = s["modbus"]["unit"]
    before = self.clock_drift
    t = time.localtime()
    self.master.write(unit, 300, regs_mod.clock_words(t))
    back = self.master.read(unit, "holding", 300, 6)
    clock = regs_mod.decode({"kind": "clock"}, back)
    self.last_clock_sync = time.time()
    with self.lock:
      if "clock" in self.values:
        self.values["clock"], self.raw["clock"] = clock, back
    self._clock_check(dict(s, clock_sync=False), clock, time.mktime(t))
    logger.info(f"Nilan clock set to {clock} by {source}" + (f" (was {before:+d} s off)" if before is not None else ""))
    return {"ok": True, "value": clock}

  def _set_schedule(self, s, payload, source):
    text = str(payload).strip().upper()
    if text not in ("ON", "OFF"):
      raise ValueError("schedule: expected ON or OFF")
    new = self.settings.get()
    new["schedule"]["enabled"] = text == "ON"
    self.settings.update(new, who=source)
    return {"ok": True, "value": text}

  def _job(self, s, req):
    try:
      if req.key is None:                                  # connection test
        m = s["modbus"]
        bus = self.master.read(m["unit"], "input", 0, 1)[0]
        dtype = self.master.read(m["unit"], "holding", 1000, 1)[0]
        req.result = {"ok": True, "bus_version": bus,
                      "device_type": regs_mod.DEVICE_TYPES.get(dtype, f"type {dtype}")}
        logger.info(f"connection test: unit {m['unit']} answers, bus version {bus}, {req.result['device_type']}")
        with self.lock:
          self.st["test"] = dict(req.result, t=time.time())
        return
      if req.key == "sync_clock":
        req.result = self._sync_clock(s, req.source)
      elif req.key == "schedule":
        req.result = self._set_schedule(s, req.value, req.source)
      else:
        req.result = self._do_write(s, req.key, req.value, req.source)
    except Exception as e:           # keep the only Modbus thread alive whatever goes wrong
      if not isinstance(e, (modbus_rtu.ModbusError, ValueError, OSError)):
        logger.exception(f"unexpected error in {req.key}")
      req.result = {"ok": False, "error": str(e)}
      if req.key is None:
        logger.warning(f"connection test failed: {e}")
        with self.lock:
          self.st["test"] = dict(req.result, t=time.time())
        return
      logger.warning(f"write {req.key} = {req.value!r} by {req.source} refused/failed: {e}")
    finally:
      if req.key is not None:
        with self.lock:
          self.st["writes_ok" if req.result.get("ok") else "writes_failed"] += 1
          self.st["last_write"] = {"t": time.time(), "key": req.key, "value": str(req.value)[:40],
                                   "source": req.source, **req.result}
        self._publish_state(self.settings.get())
      req.done.set()

  # ---- schedule ----
  def _set_schedule_applied(self, applied):
    self.schedule_applied = applied
    try:
      sched.save_state(applied, SCHEDULE_STATE_FILE)
    except OSError as e:
      logger.warning(f"could not save the schedule state: {e}")

  def _run_schedule(self, s, now=None):
    """Apply the current period once when it starts (or right after the schedule was saved)"""
    if not s["schedule"]["enabled"] or not s["modbus"]["port"]:
      return
    now = now or datetime.datetime.now()
    start, p = sched.current(s["schedule"]["periods"], now)
    if p is None or sched.period_id(start) == self.schedule_applied:
      return
    self._set_schedule_applied(sched.period_id(start))
    what = sched.label(start, p)
    logger.info(f"schedule: {what}")
    results = []
    for key, value in (("ventilation_step", p["step"]), ("temp_setpoint", p["temp"])):
      if value is None:
        continue
      req = WriteRequest(key, value, "schedule")
      self._job(s, req)
      results.append(f"{key}: {'ok' if req.result.get('ok') else req.result.get('error')}")
    with self.lock:
      self.st["last_schedule"] = {"t": time.time(), "period": what, "results": results}

  # ---- loop ----
  def run(self):
    next_read = 0
    while not self.stopper.is_set():
      s = self.settings.get()
      try:
        while True:
          self._job(s, self.jobs.get_nowait())
      except queue.Empty:
        pass
      s = self.settings.get()
      if self.announce_wanted.is_set():
        self._announce(s)
      self._run_schedule(s)
      if s["modbus"]["port"] and (self.read_wanted or time.time() >= next_read):
        self.read_wanted = False
        self._read(s)
        next_read = time.time() + s["interval_s"]
      self.wake.wait(max(0.2, min(5.0, next_read - time.time())))
      self.wake.clear()

  def stop(self):
    self.stopper.set()
    self.wake.set()
    self.join(5)
    self.bridge.stop()
    self.master.close()
