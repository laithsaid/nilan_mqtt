"""
MQTT client (paho-mqtt 1.6 or 2.x). Connects with the settings from the page and reconnects by itself;
new broker settings replace the connection.

  <topic>/lwt           online / offline (retained; offline is the last will)
  <topic>/set/<key>     commands from Home Assistant -> on_command(key, payload)
"""

import threading

import paho.mqtt.client as paho

import logs

logger = logs.get("mqtt")
CONNECTION_KEYS = ("host", "port", "username", "password", "client_id", "topic")


class Bridge:
  def __init__(self, on_command, on_connected):
    self.on_command = on_command
    self.on_connected = on_connected
    self.lock = threading.Lock()
    self.client = None
    self.cfg = None
    self.connected = False
    self.last_error = None
    self.published = 0

  # ---- connection ----
  def apply(self, mqtt_cfg):
    """(Re)connect when the broker settings changed"""
    with self.lock:
      if self.cfg and all(self.cfg[k] == mqtt_cfg[k] for k in CONNECTION_KEYS):
        self.cfg = dict(mqtt_cfg)
        return
      self._stop()
      self.cfg = dict(mqtt_cfg)
      if not mqtt_cfg["host"]:
        self.last_error = "no broker set"
        logger.warning("MQTT: no broker set on the page; not connecting")
        return
      if hasattr(paho, "CallbackAPIVersion"):       # paho-mqtt 2.x
        c = paho.Client(paho.CallbackAPIVersion.VERSION1, client_id=mqtt_cfg["client_id"], clean_session=True)
      else:
        c = paho.Client(client_id=mqtt_cfg["client_id"], clean_session=True)
      if mqtt_cfg["username"]:
        c.username_pw_set(mqtt_cfg["username"], mqtt_cfg["password"] or None)
      c.will_set(self.lwt_topic(), "offline", qos=1, retain=True)
      c.reconnect_delay_set(min_delay=1, max_delay=120)
      c.on_connect = self._on_connect
      c.on_disconnect = self._on_disconnect
      c.on_message = self._on_message
      c.on_connect_fail = self._on_connect_fail
      c.connect_async(mqtt_cfg["host"], mqtt_cfg["port"], keepalive=60)
      c.loop_start()
      self.client = c
      logger.info(f"MQTT: connecting to {mqtt_cfg['host']}:{mqtt_cfg['port']} as {mqtt_cfg['username'] or '(no user)'}")

  def stop(self):
    with self.lock:
      self._stop()

  def _stop(self):
    if self.client is not None:
      c, self.client = self.client, None
      try:
        if self.connected:
          c.publish(self.lwt_topic(), "offline", qos=1, retain=True).wait_for_publish(2)
        c.disconnect()
      except Exception as e:
        logger.debug(f"MQTT: stop: {e}")
      c.loop_stop()
      self.connected = False

  def lwt_topic(self):
    return self.cfg["topic"] + "/lwt"

  def _on_connect(self, client, _userdata, _flags, rc, _properties=None):
    if client is not self.client:
      return
    if rc != 0:
      self.connected = False
      self.last_error = f"connection refused: {paho.connack_string(rc)}"
      logger.error(f"MQTT: {self.last_error}")
      return
    self.connected = True
    self.last_error = None
    logger.info(f"MQTT: connected to {self.cfg['host']}")
    client.subscribe(self.cfg["topic"] + "/set/+", qos=1)
    client.publish(self.lwt_topic(), "online", qos=1, retain=True)
    self.on_connected()

  def _on_connect_fail(self, client, _userdata):
    if client is not self.client:
      return
    error = f"can't reach the broker {self.cfg['host']}:{self.cfg['port']}"
    if self.last_error != error:
      logger.warning(f"MQTT: {error}; retrying")
    self.last_error = error

  def _on_disconnect(self, client, _userdata, rc, _properties=None):
    if client is not self.client:
      return
    self.connected = False
    if rc != 0:
      self.last_error = f"connection lost ({paho.error_string(rc)})"
      logger.warning(f"MQTT: {self.last_error}; reconnecting")

  def _on_message(self, client, _userdata, msg):
    if client is not self.client:
      return
    prefix = self.cfg["topic"] + "/set/"
    if msg.topic.startswith(prefix):
      try:
        payload = msg.payload.decode("utf-8")[:100]
      except UnicodeDecodeError:
        logger.warning(f"MQTT: ignoring non-text command on {msg.topic}")
        return
      self.on_command(msg.topic[len(prefix):], payload)

  # ---- publishing ----
  def publish(self, topic, payload, retain=False, qos=1):
    c = self.client
    if c is None or not self.connected:
      return False
    info = c.publish(topic, payload, qos=qos, retain=retain)
    if info.rc != paho.MQTT_ERR_SUCCESS:
      logger.warning(f"MQTT: publish to {topic} failed: {paho.error_string(info.rc)}")
      return False
    self.published += 1
    return True

  def status(self):
    return {"connected": self.connected, "last_error": self.last_error, "published": self.published,
            "broker": f"{self.cfg['host']}:{self.cfg['port']}" if self.cfg and self.cfg["host"] else ""}
