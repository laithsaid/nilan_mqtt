"""
Password-protected web page (standard library only), same design as the heat-meter and flowIQ readers:
  GET  /login          login form
  POST /api/login      {username, password} -> session cookie
  POST /api/logout
  GET  /               the page
  GET  /api/state      values, register table, statistics, settings (without the MQTT password), version
  GET  /api/logs       log lines after ?after=<seq>
  POST /api/settings   new settings
  POST /api/write      {key, value}: write one register (only access = write, inside its limits);
                       key "sync_clock" sets the Nilan clock, key "schedule" (ON/OFF) the week schedule
  POST /api/read       read now
  POST /api/test       connection test (bus version + device type)
All POSTs need the header X-Requested-With: nilan-web (CSRF guard).

Password: web_auth.json (web_password.py); without it the page does not start.
HTTPS: web_cert.pem / web_key.pem next to this file, or WEB_TLS_CERT / WEB_TLS_KEY in config.py.
"""

import hashlib
import hmac
import http.cookies
import json
import os
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import config as cfg
import logs
import registers as regs_mod
import settings as settings_mod

logger = logs.get("web")

HERE = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(HERE, "web_auth.json")
PAGE_FILE = os.path.join(HERE, "web", "index.html")
LOGIN_FILE = os.path.join(HERE, "web", "login.html")
CERT_FILE = os.path.join(HERE, "web_cert.pem")
KEY_FILE = os.path.join(HERE, "web_key.pem")

MAX_FAILURES = 10
LOCKOUT_S = 300
MAX_BODY = 256 * 1024
# Cookies are shared by all ports of a host: differs from kamstrup_session (:8080) and flowiq_session (:8081)
SESSION_COOKIE = "nilan_session"
SESSION_S = 7 * 24 * 3600
MAX_SESSIONS = 50
CSRF_HEADER = "nilan-web"


class _Auth:
  def __init__(self, path):
    with open(path, encoding="utf-8") as f:
      data = json.load(f)
    self.username = data["username"]
    self.salt = bytes.fromhex(data["salt"])
    self.iterations = int(data["iterations"])
    self.hash = data["hash"]
    self.failures = {}
    self.sessions = {}
    self.lock = threading.Lock()

  def locked_out(self, ip):
    with self.lock:
      recent = [t for t in self.failures.get(ip, []) if time.time() - t < LOCKOUT_S]
      self.failures[ip] = recent
      return len(recent) >= MAX_FAILURES

  def login(self, user, password, ip):
    candidate = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), self.salt, self.iterations).hex()
    user_ok = hmac.compare_digest(str(user).encode("utf-8"), self.username.encode("utf-8"))
    if not (hmac.compare_digest(candidate, self.hash) and user_ok):
      with self.lock:
        self.failures.setdefault(ip, []).append(time.time())
      logger.warning(f"Web: wrong user name or password from {ip}")
      return None
    token = secrets.token_urlsafe(32)
    with self.lock:
      now = time.time()
      self.sessions = {t: exp for t, exp in self.sessions.items() if exp > now}
      if len(self.sessions) >= MAX_SESSIONS:
        del self.sessions[min(self.sessions, key=self.sessions.get)]
      self.sessions[token] = now + SESSION_S
    logger.info(f"Web: {self.username} logged in from {ip}")
    return token

  def valid(self, token):
    with self.lock:
      exp = self.sessions.get(token or "")
      return exp is not None and exp > time.time()

  def logout(self, token):
    with self.lock:
      self.sessions.pop(token or "", None)


def serial_ports():
  by_id = "/dev/serial/by-id"
  try:
    return sorted(os.path.join(by_id, n) for n in os.listdir(by_id))
  except OSError:
    return []


def _json_safe(r):
  """Register definition for the page (enum options with string keys)"""
  out = dict(r)
  out["range"] = regs_mod.range_text(r)
  if "options" in out:
    out["options"] = {str(k): v for k, v in out["options"].items()}
  return out


def _make_handler(auth, settings, poller, version, secure):

  class Handler(BaseHTTPRequestHandler):
    server_version = "nilan-web"
    sys_version = ""

    def log_message(self, fmt, *args):
      logger.debug("Web: " + fmt % args)

    def _send(self, code, body, content_type="application/json", extra_headers=()):
      if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
      if isinstance(body, str):
        body = body.encode("utf-8")
      self.send_response(code)
      self.send_header("Content-Type", content_type + "; charset=utf-8")
      self.send_header("Content-Length", str(len(body)))
      self.send_header("Cache-Control", "no-store")
      self.send_header("X-Frame-Options", "DENY")
      self.send_header("X-Content-Type-Options", "nosniff")
      self.send_header("Referrer-Policy", "no-referrer")
      self.send_header("Content-Security-Policy",
                       "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                       "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'")
      for name, value in extra_headers:
        self.send_header(name, value)
      self.end_headers()
      self.wfile.write(body)

    def _token(self):
      cookie = http.cookies.SimpleCookie()
      try:
        cookie.load(self.headers.get("Cookie") or "")
      except http.cookies.CookieError:
        return None
      return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None

    def _cookie(self, token, max_age):
      return ("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
                            + ("; Secure" if secure else ""))

    def _logged_in(self, html=False):
      if auth.valid(self._token()):
        return True
      if html:
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Content-Length", "0")
        self.end_headers()
      else:
        self._send(401, {"error": "not logged in"})
      return False

    def _read_json(self):
      if self.headers.get("X-Requested-With") != CSRF_HEADER or \
         not (self.headers.get("Content-Type") or "").startswith("application/json"):
        self._send(403, {"error": "missing X-Requested-With or JSON content type"})
        return None
      length = int(self.headers.get("Content-Length") or 0)
      if not 0 < length <= MAX_BODY:
        self._send(413, {"error": "body too large or empty"})
        return None
      try:
        return json.loads(self.rfile.read(length))
      except ValueError:
        self._send(400, {"error": "body is not JSON"})
        return None

    def _who(self):
      return f"{auth.username} from {self.client_address[0]} (web)"

    def _state(self):
      s = settings.get()
      snap = poller.snapshot()
      snap.update(now=time.time(), version=version, settings=settings_mod.public(s), serial_ports=serial_ports(),
                  table=[_json_safe(r) for r in settings_mod.effective(s)],
                  builtin={r["key"]: _json_safe(r) for r in regs_mod.BUILTIN},
                  limits={"min_interval_s": settings_mod.MIN_INTERVAL_S, "max_interval_s": settings_mod.MAX_INTERVAL_S})
      return snap

    def do_GET(self):
      path = self.path.split("?")[0]
      if path == "/login":
        with open(LOGIN_FILE, encoding="utf-8") as f:
          return self._send(200, f.read(), "text/html")
      if path in ("/", "/index.html"):
        if self._logged_in(html=True):
          with open(PAGE_FILE, encoding="utf-8") as f:
            self._send(200, f.read(), "text/html")
      elif path == "/api/state":
        if self._logged_in():
          self._send(200, self._state())
      elif path == "/api/logs":
        if self._logged_in():
          try:
            after = int(parse_qs(self.path.partition("?")[2]).get("after", ["0"])[0])
          except ValueError:
            after = 0
          lines, last = logs.ring.since(after)
          self._send(200, {"lines": lines, "last": last})
      else:
        self._send(404, {"error": "not found"})

    def do_POST(self):
      path = self.path.split("?")[0]
      if path == "/api/login":
        ip = self.client_address[0]
        if auth.locked_out(ip):
          return self._send(429, {"error": "too many wrong passwords; try again in a few minutes"})
        body = self._read_json()
        if body is None:
          return
        if not isinstance(body, dict):
          return self._send(400, {"error": "expected {username, password}"})
        token = auth.login(body.get("username", ""), body.get("password", ""), ip)
        if token is None:
          time.sleep(1)
          return self._send(401, {"error": "wrong user name or password"})
        return self._send(200, {"ok": True}, extra_headers=[self._cookie(token, SESSION_S)])
      if path == "/api/logout":
        if self._read_json() is None:
          return
        if auth.valid(self._token()):
          logger.info(f"Web: {auth.username} logged out from {self.client_address[0]}")
        auth.logout(self._token())
        return self._send(200, {"ok": True}, extra_headers=[self._cookie("", 0)])

      if path not in ("/api/settings", "/api/write", "/api/read", "/api/test"):
        return self._send(404, {"error": "not found"})
      if not self._logged_in():
        return
      body = self._read_json()
      if body is None:
        return
      if path == "/api/read":
        poller.request_read()
        return self._send(200, {"ok": True})
      if path == "/api/test":
        return self._send(200, poller.test())
      if path == "/api/write":
        if not isinstance(body, dict) or not isinstance(body.get("key"), str) or "value" not in body:
          return self._send(400, {"error": "expected {key, value}"})
        result = poller.write(body["key"], str(body["value"])[:100], self._who())
        return self._send(200 if result.get("ok") else 400, result)
      try:
        settings.update(body, who=self._who())
      except ValueError as e:
        return self._send(400, {"error": str(e)})
      except OSError as e:
        logger.error(f"Web: could not save settings: {e}")
        return self._send(500, {"error": f"could not save settings: {e}"})
      self._send(200, self._state())

  return Handler


class _Server(ThreadingHTTPServer):
  daemon_threads = True

  def handle_error(self, request, client_address):
    logger.debug(f"Web: connection from {client_address[0]} failed", exc_info=True)


def start(settings, poller, version=""):
  """Start the page in a daemon thread. Returns the server, or None when it can't start."""
  port = getattr(cfg, "WEB_PORT", 8082)
  if not port:
    logger.info("Web page disabled (WEB_PORT = 0)")
    return None
  try:
    auth = _Auth(AUTH_FILE)
  except (OSError, KeyError, ValueError) as e:
    logger.error(f"Web page NOT started: no valid {AUTH_FILE} ({e}). Run: python3 web_password.py")
    return None

  cert = getattr(cfg, "WEB_TLS_CERT", None) or CERT_FILE
  key = getattr(cfg, "WEB_TLS_KEY", None) or KEY_FILE
  context = None
  if os.path.exists(cert) or os.path.exists(key) or not getattr(cfg, "WEB_ALLOW_HTTP", False):
    try:
      context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
      context.minimum_version = ssl.TLSVersion.TLSv1_2
      context.load_cert_chain(cert, key)
    except (OSError, ssl.SSLError) as e:
      logger.error(f"Web page NOT started: could not load {cert} / {key} ({e}). Run: sh tools/make_web_cert.sh")
      return None

  try:
    server = _Server((getattr(cfg, "WEB_BIND", "0.0.0.0"), port),
                     _make_handler(auth, settings, poller, version, context is not None))
  except OSError as e:
    logger.error(f"Web page NOT started: port {port}: {e}")
    return None
  scheme = "http"
  if context:
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    scheme = "https"
  else:
    logger.warning("Web page runs WITHOUT HTTPS (WEB_ALLOW_HTTP = True): the password is sent unencrypted")
  threading.Thread(target=server.serve_forever, name="web", daemon=True).start()
  logger.info(f"Web page on {scheme}://<pi>:{port}/")
  return server
