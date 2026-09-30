"""
nilan-mqtt configuration that needs a restart. Everything else (serial port, Modbus, MQTT broker and login,
registers, interval) is set on the web page and saved in settings.json.
"""

# DEBUG, INFO, WARNING, ERROR
loglevel = "INFO"

# [ Web page ] https://<pi>:8082/ (0 = off). Once, on the Pi, in this folder:
#   python3 web_password.py            user name + password
#   sh tools/make_web_cert.sh          HTTPS certificate (web_cert.pem / web_key.pem next to this file)
WEB_PORT = 8082
WEB_BIND = "0.0.0.0"
# Other certificate files than web_cert.pem / web_key.pem next to this file, e.g. the heat-meter reader's
# certificate on the same Pi (then the PC needs no second CA import):
# WEB_TLS_CERT = "/home/laith/kamstrup2mqtt-main/web_cert.pem"
# WEB_TLS_KEY = "/home/laith/kamstrup2mqtt-main/web_key.pem"
# Without a certificate the page does not start. Plain HTTP (password unencrypted) only with:
# WEB_ALLOW_HTTP = True
