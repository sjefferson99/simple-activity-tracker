#!/usr/bin/env bash
# Generates a self-signed cert for the nginx proxy in this deployment.
# Usage: ./generate-cert.sh <hostname-or-IP> [days]
#
# The phone/browser will show a "not trusted" warning until you either accept
# it once per client, or install certs/cert.pem as a trusted root. That's
# expected for a self-signed cert — for a browser-trusted cert with no manual
# steps, use a reverse proxy with real ACME/certificate management instead
# (see README.md "Using a different reverse proxy").
set -euo pipefail

HOST="${1:?Usage: ./generate-cert.sh <hostname-or-IP> [days]}"
DAYS="${2:-825}"
CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/certs"
mkdir -p "$CERT_DIR"

SAN="DNS:${HOST}"
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN="IP:${HOST}"
fi

# The leading "//" (instead of "/") works around Git Bash/MSYS mangling a
# single-leading-slash -subj value into a Windows path (e.g. "/CN=x" becomes
# "C:/Program Files/Git/CN=x"). OpenSSL accepts both forms identically.
SUBJ="/CN=${HOST}"
[[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]] && SUBJ="/${SUBJ}"

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$CERT_DIR/key.pem" \
  -out "$CERT_DIR/cert.pem" \
  -days "$DAYS" \
  -subj "$SUBJ" \
  -addext "subjectAltName=${SAN}"

# Recent OpenSSL versions write -keyout at mode 600 regardless of umask —
# fine for whoever ran this script, but the proxy container's nginx runs as
# its own "nginx" user (see docker-compose.yml), which then can't read the
# key at all ("Permission denied") and restart-loops. There's no secret here
# worth protecting beyond what's already true of every other file in this
# directory (readable by anyone who can reach this host/repo checkout), so
# loosen it to match cert.pem instead of chasing per-container UIDs.
chmod 644 "$CERT_DIR/key.pem"

echo "Wrote $CERT_DIR/cert.pem and $CERT_DIR/key.pem (valid $DAYS days, SAN=$SAN)"
