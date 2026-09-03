# Standalone deployment with a self-signed cert

Runs the app behind an nginx sidecar that terminates HTTPS with a self-signed
certificate — no external reverse proxy, no ACME, no domain required. This is
the deployment guide for the project: works as-is for a homelab box, a Pi
(same multi-arch image, same compose file), or plain LAN use, and doubles as
a template if you later want to swap in a reverse proxy with real certificate
management (see "Using a different reverse proxy" below).

## Setup

```bash
cd deploy/standalone-tls
cp .env.example .env            # fill in SR_SECRET_KEY, SR_ADMIN_EMAIL, SR_ADMIN_PASSWORD
./generate-cert.sh <your-LAN-IP-or-hostname>
docker compose up -d
```

Browse to `https://<host>/` — you'll get a certificate warning (expected,
it's self-signed); accept it to continue. The phone app can point at the same
`https://` URL with no cleartext warning, since the connection is genuinely
encrypted even though the cert isn't from a public CA.

To trust the cert instead of clicking through the warning every time, install
`certs/cert.pem` as a trusted root on each client device.

`app` runs the published image (`ghcr.io/sjefferson99/simple-runner-server:latest`,
the same one CI pushes on every merge to `main`) — to update to the latest
version later: `docker compose pull app && docker compose up -d`.

## Ports

- `proxy` publishes **80** (redirects to 443) and **443** (TLS) — these are
  what a router/firewall needs to forward for LAN or WAN access.
- `app` publishes nothing; it's reached by `proxy` over the compose network
  only, on port 8000.

## Running on a Raspberry Pi

No changes needed — the GHCR image is published for both `linux/amd64` and
`linux/arm64`, and `nginx:alpine` is multi-arch too, so `docker compose pull
&& docker compose up -d` on a 64-bit Pi OS pulls the right image automatically.

## Using a different reverse proxy

If you later want a proxy with real (non-self-signed) certificate management —
Traefik with an ACME resolver, Caddy's automatic HTTPS, nginx-proxy, etc. —
the `app` service needs no changes either way, since TLS termination has
always been out of scope for the container itself (docs/WEB-PLAN.md §5.6):

1. Delete the `proxy` service (and `./certs`, `nginx.conf`) — your proxy replaces it.
2. Point your proxy's routing config at `app:8000` (or join `app` to whatever
   network your proxy uses, and set the equivalent of `loadbalancer.server.port`).
3. Remove `app`'s `expose:` if the new proxy needs a different network layout.
4. Point `SR_TRUSTED_PROXIES` at the new proxy's network range.
