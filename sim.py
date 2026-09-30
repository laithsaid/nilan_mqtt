"""
A fake Nilan CTS 602 on a fake serial port (serial port "simulate" on the page, and the tests).
Answers Modbus RTU frames byte for byte like the real unit: functions 03, 04 and 16, exception 2 for unknown
registers. Values are what our unit answered on 2026-09-30.
"""

import struct
import threading

from modbus_rtu import crc16

INPUT = {0: 5, 1: 11826, 2: 12594, 3: 30720, 100: 0, 101: 1, 102: 0, 103: 0, 104: 0, 105: 1, 106: 0, 113: 0,
         200: 2774, 201: 0, 202: 0, 203: 2188, 204: 1728, 205: 0, 206: 0, 207: 2121, 208: 1490, 209: 61536,
         210: 61536, 215: 2544, 221: 5985, 222: 0, 400: 0, 401: 0, 402: 0, 403: 0, 404: 0, 405: 0, 406: 0, 407: 0,
         408: 0, 409: 0, 1000: 1, 1001: 3, 1002: 7, 1003: 55103, 1200: 0, 1201: 1934, 1202: 2188, 1203: 2545,
         1204: 5990, 1205: 0, 1206: 0, 2000: 0, 2001: 0, 2002: 21825, 2003: 20308, 2004: 8224, 2005: 12576,
         2006: 0, 2007: 12606, 2008: 8252, 2009: 12850, 2010: 17375, 2011: 0}
HOLDING = {200: 10000, 201: 9000, 400: 0, 500: 1, 600: 0, 601: 0, 602: 0, 603: 2, 604: 23, 605: 0, 610: 0, 611: 0,
           612: 0, 613: 4, 614: 23, 615: 0, 1000: 13, 1001: 1, 1002: 3, 1003: 1, 1004: 2200, 1005: 0, 1006: 5000,
           1007: 0, 1100: 1, 1101: 3, 1200: 0, 1201: 1400, 1202: 1700, 1203: 2200, 1204: 2500, 1205: 1800, 1910: 2,
           1911: 4, 1912: 3000, 1913: 0, 1920: 3, 1921: 600, 1922: 800}
UNIT = 30


class FakeNilan:
  """Serial-port lookalike: write() a request, read() the answer"""

  def __init__(self, unit=UNIT, **_ignored):
    self.unit = unit
    self.input = dict(INPUT)
    self.holding = dict(HOLDING)
    self.out = b""
    self.lock = threading.Lock()
    self.silent = False          # tests: pretend the unit is unplugged
    self.writes = []

  def close(self):
    pass

  def reset_input_buffer(self):
    self.out = b""

  def read(self, n):
    data, self.out = self.out[:n], self.out[n:]
    return data

  def _answer(self, pdu):
    return pdu + crc16(pdu)

  def write(self, frame):
    with self.lock:
      if self.silent or len(frame) < 8 or crc16(frame[:-2]) != frame[-2:] or frame[0] != self.unit:
        return
      fc = frame[1]
      if fc in (3, 4):
        address, count = struct.unpack(">HH", frame[2:6])
        table = self.holding if fc == 3 else self.input
        if any(a not in table for a in range(address, address + count)):
          self.out = self._answer(bytes([self.unit, fc | 0x80, 2]))
          return
        words = [table[a] for a in range(address, address + count)]
        self.out = self._answer(bytes([self.unit, fc, 2 * count]) + struct.pack(f">{count}H", *words))
      elif fc == 16:
        address, count = struct.unpack(">HH", frame[2:6])
        words = struct.unpack(f">{count}H", frame[7:7 + 2 * count])
        if any(a not in self.holding for a in range(address, address + count)):
          self.out = self._answer(bytes([self.unit, fc | 0x80, 2]))
          return
        for i, w in enumerate(words):
          self.holding[address + i] = w
          self.writes.append((address + i, w))
          if address + i == 1001:        # run on/off shows in the input registers too
            self.input[1000] = w
        self.out = self._answer(frame[:6])
      else:
        self.out = self._answer(bytes([self.unit, fc | 0x80, 1]))
