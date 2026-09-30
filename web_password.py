#!/usr/bin/python3
"""
  Set the user name and password for the web page.

  sudo python3 web_password.py            (asks for user name and password)

  Writes web_auth.json next to this script (salted PBKDF2 hash, not the password).
  The web page does not start without this file. Restart the service afterwards.
"""

import getpass
import hashlib
import json
import os
import secrets
import sys

ITERATIONS = 200_000
AUTH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_auth.json")


def make_hash(password, salt, iterations=ITERATIONS):
  return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def main():
  user = input("User name [admin]: ").strip() or "admin"
  password = getpass.getpass("Password (min 10 characters): ")
  if len(password) < 10:
    sys.exit("Too short; nothing written.")
  if getpass.getpass("Repeat password: ") != password:
    sys.exit("Passwords differ; nothing written.")

  salt = secrets.token_bytes(16)
  data = {"username": user, "salt": salt.hex(), "iterations": ITERATIONS, "hash": make_hash(password, salt)}

  # Readable by the owner only
  fd = os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  with os.fdopen(fd, "w") as f:
    json.dump(data, f)
  print(f"Written {AUTH_FILE}. Restart the service: sudo systemctl restart nilan-mqtt")


if __name__ == "__main__":
  main()
