#!/bin/sh
# HTTPS certificate for the web page, signed by a small local CA (valid 10 years).
#
#   sudo sh tools/make_web_cert.sh [ip-or-name ...]      default: this Pi's IP addresses + hostname
#
# Writes next to nilan-mqtt.py:
#   web_ca.pem    import this on your PC as a trusted root -> no browser warning
#   web_cert.pem  the Pi's certificate
#   web_key.pem   the Pi's private key (mode 600)
# The CA may only sign the names/addresses given here (name constraints), and its private key
# is deleted right after signing, so web_ca.pem can't be used to fake any other site.
# Running the script again makes a new CA: import the new web_ca.pem again.
#
# Then set in config.py and restart (sudo systemctl restart nilan-mqtt):
#   WEB_TLS_CERT = "<folder>/web_cert.pem"
#   WEB_TLS_KEY = "<folder>/web_key.pem"
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAMES="$*"
[ -n "$NAMES" ] || NAMES="$(hostname -I) $(hostname) $(hostname).local localhost"

SAN=""
PERMIT=""
for n in $NAMES; do
  case "$n" in
    *:*) SAN="$SAN,IP:$n"; PERMIT="$PERMIT,permitted;IP:$n/ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff" ;;
    *[!0-9.]*) SAN="$SAN,DNS:$n"; PERMIT="$PERMIT,permitted;DNS:$n" ;;
    *) SAN="$SAN,IP:$n"; PERMIT="$PERMIT,permitted;IP:$n/255.255.255.255" ;;
  esac
done
SAN="${SAN#,}"
PERMIT="${PERMIT#,}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
umask 077

cat > "$WORK/openssl.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = Kamstrup reader local CA $(hostname) $(date +%Y-%m-%d)
[ca]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
nameConstraints = critical,$PERMIT
subjectKeyIdentifier = hash
[server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = $SAN
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
EOF

# Local CA (its key only lives in $WORK and is deleted on exit)
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
  -config "$WORK/openssl.cnf" -extensions ca -keyout "$WORK/ca_key.pem" -out "$DIR/web_ca.pem"

# Server key + certificate signed by the CA
openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -subj "/CN=Kamstrup reader $(hostname)" -keyout "$DIR/web_key.pem" -out "$WORK/server.csr"
openssl x509 -req -in "$WORK/server.csr" -CA "$DIR/web_ca.pem" -CAkey "$WORK/ca_key.pem" -set_serial "0x$(openssl rand -hex 16)" \
  -days 3650 -sha256 -extfile "$WORK/openssl.cnf" -extensions server -out "$DIR/web_cert.pem"

chmod 600 "$DIR/web_key.pem"
chmod 644 "$DIR/web_cert.pem" "$DIR/web_ca.pem"
openssl verify -CAfile "$DIR/web_ca.pem" "$DIR/web_cert.pem"

echo "Certificate for: $SAN"
echo "Import on your PC as a trusted root: $DIR/web_ca.pem"
openssl x509 -in "$DIR/web_ca.pem" -noout -fingerprint -sha256
