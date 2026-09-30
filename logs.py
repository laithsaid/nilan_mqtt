"""
Logging: console (journal), syslog on Linux, and a memory ring of the last RING_SIZE INFO/WARNING/ERROR lines for
the web page's Log card. Import `logger` in the main module; other modules use logging.getLogger("nilan-mqtt.<name>").
"""

import collections
import logging
import logging.handlers
import sys
import threading

NAME = "nilan-mqtt"
RING_SIZE = 1000

logger = logging.getLogger(NAME)
logger.setLevel(logging.INFO)
logger.propagate = False

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter("%(name)s %(levelname)s: %(message)s"))
logger.addHandler(_console)


class RingHandler(logging.Handler):
  """Keeps the last lines; since(seq) returns the ones after seq (each line has a running number)"""

  def __init__(self, size=RING_SIZE):
    super().__init__()
    self.__lines = collections.deque(maxlen=size)
    self.__seq = 0
    self.__lock = threading.Lock()

  def emit(self, record):
    try:
      message = record.getMessage()
    except Exception:
      message = str(record.msg)
    with self.__lock:
      self.__seq += 1
      self.__lines.append({"seq": self.__seq, "t": record.created, "level": record.levelname,
                           "source": record.name.split(".", 1)[-1], "where": f"{record.funcName}:{record.lineno}",
                           "message": message})

  def since(self, seq=0):
    with self.__lock:
      return [line for line in self.__lines if line["seq"] > seq], self.__seq


ring = RingHandler()
ring.setLevel(logging.INFO)
logger.addHandler(ring)


def get(name):
  return logging.getLogger(f"{NAME}.{name}")
