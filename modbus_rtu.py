"""
Modbus RTU master over a serial port (pyserial only, no pymodbus).

  read(unit, table, address, count)   function 03 (holding) / 04 (input); returns a list of 16-bit unsigned words
  write(unit, address, words)         function 16 (write multiple holding registers)

One transaction at a time (lock). The port is opened on first use and closed after an I/O error, so an unplugged
USB adapter is picked up again on the next call. Timeouts and CRC errors are retried; an exception answer from the
slave (e.g. 2 = illegal address) is not.
"""

import struct
import threading
import time

import serial

EXCEPTIONS = {1: "illegal function", 2: "illegal data address", 3: "illegal data value", 4: "slave device failure",
              5: "acknowledge", 6: "slave device busy", 8: "memory parity error", 10: "gateway path unavailable",
              11: "gateway target failed to respond"}
MAX_READ = 125           # Modbus limit per read
MAX_WRITE = 123


class ModbusError(Exception):
  """No or bad answer (timeout, CRC, wrong frame, port problem)"""


class ModbusException(ModbusError):
  """The slave answered with a Modbus exception code"""

  def __init__(self, code):
    self.code = code
    super().__init__(f"exception {code} ({EXCEPTIONS.get(code, 'unknown')})")


def crc16(data):
  crc = 0xFFFF
  for b in data:
    crc ^= b
    for _ in range(8):
      crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
  return struct.pack("<H", crc)


def read_request(unit, fc, address, count):
  pdu = struct.pack(">BBHH", unit, fc, address, count)
  return pdu + crc16(pdu)


def write_request(unit, address, words):
  pdu = struct.pack(">BBHHB", unit, 16, address, len(words), 2 * len(words)) + struct.pack(f">{len(words)}H", *words)
  return pdu + crc16(pdu)


class RtuMaster:
  def __init__(self, port="", baudrate=19200, bytesize=8, parity="E", stopbits=1, timeout=0.5, retries=2,
               gap_s=0.02, serial_factory=None):
    self.lock = threading.Lock()
    self.ser = None
    self.serial_factory = serial_factory or serial.Serial
    self.configure(port, baudrate, bytesize, parity, stopbits, timeout, retries, gap_s)
    self.last_io = 0.0

  def configure(self, port, baudrate=19200, bytesize=8, parity="E", stopbits=1, timeout=0.5, retries=2, gap_s=0.02):
    """New serial settings: the port is reopened on the next transaction"""
    with self.lock:
      self._close()
      self.params = dict(port=port, baudrate=baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits)
      self.timeout = timeout
      self.retries = retries
      self.gap_s = gap_s

  def close(self):
    with self.lock:
      self._close()

  def _close(self):
    if self.ser is not None:
      try:
        self.ser.close()
      except Exception:
        pass
      self.ser = None

  def _open(self):
    if self.ser is None:
      if not self.params["port"]:
        raise ModbusError("no serial port set")
      try:
        self.ser = self.serial_factory(timeout=self.timeout, **self.params)
      except (serial.SerialException, OSError, ValueError) as e:
        raise ModbusError(f"can't open {self.params['port']}: {e}")
    return self.ser

  def _exchange(self, request, answer_len):
    """Send one frame and return the checked answer (without CRC). Retries timeouts and bad frames."""
    unit, fc = request[0], request[1]
    last = None
    for _ in range(1 + self.retries):
      ser = self._open()
      try:
        # Silent interval between frames (3.5 characters, at least gap_s)
        wait = self.last_io + self.gap_s - time.monotonic()
        if wait > 0:
          time.sleep(wait)
        ser.reset_input_buffer()
        ser.write(request)
        head = ser.read(2)
        if len(head) < 2:
          last = ModbusError("no answer (timeout)")
        elif head[0] != unit or (head[1] & 0x7F) != fc:
          ser.read(256)
          last = ModbusError(f"unexpected answer {head.hex()} for unit {unit} function {fc}")
        else:
          rest = ser.read(3 if head[1] & 0x80 else answer_len - 2)
          frame = head + rest
          if len(frame) < 5 or crc16(frame[:-2]) != frame[-2:]:
            last = ModbusError(f"bad CRC or short answer ({frame.hex()})")
          elif head[1] & 0x80:
            raise ModbusException(frame[2])
          elif len(frame) != answer_len:
            last = ModbusError(f"answer has {len(frame)} bytes, expected {answer_len}")
          else:
            return frame[:-2]
      except (serial.SerialException, OSError) as e:
        self._close()
        last = ModbusError(f"serial port error: {e}")
      finally:
        self.last_io = time.monotonic()
    raise last

  def read(self, unit, table, address, count=1):
    if table not in ("holding", "input"):
      raise ValueError("table must be holding or input")
    if not 1 <= count <= MAX_READ or not 0 <= address <= 0xFFFF - count + 1:
      raise ValueError("bad address/count")
    fc = 3 if table == "holding" else 4
    with self.lock:
      frame = self._exchange(read_request(unit, fc, address, count), 5 + 2 * count)
    if frame[2] != 2 * count:
      raise ModbusError(f"answer has {frame[2]} data bytes, expected {2 * count}")
    return list(struct.unpack(f">{count}H", frame[3:3 + 2 * count]))

  def write(self, unit, address, words):
    words = [int(w) & 0xFFFF for w in words]
    if not 1 <= len(words) <= MAX_WRITE:
      raise ValueError("bad count")
    with self.lock:
      frame = self._exchange(write_request(unit, address, words), 8)
    if struct.unpack(">HH", frame[2:6]) != (address, len(words)):
      raise ModbusError(f"write echo {frame.hex()} does not match")
