#!/usr/bin/python3
"""
nilan-mqtt: Nilan CTS 602 ventilation unit (Comfort 300) over Modbus RTU <-> MQTT / Home Assistant,
with a password-protected web page for settings, values, the register table and the log.

Threads: poller (the only one that talks Modbus), MQTT client (paho), web page.
"""

__version__ = "1.1.2"

import signal
import socket
import sys
import threading

import bridge
import config as cfg
import poller as poller_mod
import settings as settings_mod
import webserver
from logs import logger

logger.setLevel(cfg.loglevel)
stopper = threading.Event()


def main():
  if sys.platform == "linux":
    # only one instance (abstract socket, gone when the process ends)
    lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
      lock.bind("\0nilan-mqtt_lock")
    except OSError:
      logger.error("nilan-mqtt is already running")
      sys.exit(1)
  logger.info(f"Starting nilan-mqtt; version = {__version__}")
  settings = settings_mod.Settings()
  poller = poller_mod.Poller(settings, bridge.Bridge, __version__)
  webserver.start(settings, poller, __version__)
  poller.start()
  signal.signal(signal.SIGTERM, lambda *_: stopper.set())
  signal.signal(signal.SIGINT, lambda *_: stopper.set())
  while not stopper.is_set():
    stopper.wait(1)
  logger.info("Stopping")
  poller.stop()


if __name__ == "__main__":
  main()
