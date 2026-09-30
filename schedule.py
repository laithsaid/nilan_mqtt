"""
Week schedule run by this program (the Nilan's own week programs can't be read or edited over Modbus on the CTS 602
with bus version 5; only which program runs can be chosen, register 500).

A period starts on the chosen weekdays at its start time and sets the ventilation step and/or the room setpoint once.
It is not re-applied until the next period starts, so a change from the panel, the page or Home Assistant stays until
then. After a restart the current period is not applied again (the last applied period is remembered in
schedule_state.json); saving the schedule applies the current period straight away.
"""

import datetime
import json
import os

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_state.json")


def _starts(periods, now, back_days=7, ahead_days=8):
  """All period starts from back_days before to ahead_days after now: [(datetime, period)] sorted"""
  out = []
  for offset in range(-back_days, ahead_days):
    day = (now + datetime.timedelta(days=offset)).date()
    for p in periods:
      if day.weekday() in p["days"]:
        h, m = map(int, p["start"].split(":"))
        out.append((datetime.datetime.combine(day, datetime.time(h, m)), p))
  out.sort(key=lambda x: x[0])
  return out


def current(periods, now):
  """(start datetime, period) of the period running at `now`, or (None, None)"""
  last = (None, None)
  for start, p in _starts(periods, now):
    if start <= now:
      last = (start, p)
  return last


def upcoming(periods, now):
  """(start datetime, period) of the next period start after `now`, or (None, None)"""
  for start, p in _starts(periods, now):
    if start > now:
      return start, p
  return None, None


def describe(p):
  parts = []
  if p.get("step") is not None:
    parts.append(f"step {p['step']}")
  if p.get("temp") is not None:
    parts.append(f"{p['temp']:g} °C")
  return ", ".join(parts)


def label(start, p):
  return f"{DAYS[start.weekday()]} {start:%H:%M} → {describe(p)}" if start else "none"


def period_id(start):
  return start.strftime("%Y-%m-%d %H:%M") if start else None


def load_state(path=STATE_FILE):
  try:
    with open(path, encoding="utf-8") as f:
      return json.load(f).get("applied")
  except (OSError, ValueError, AttributeError):
    return None


def save_state(applied, path=STATE_FILE):
  tmp = path + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"applied": applied}, f)
  os.replace(tmp, path)
