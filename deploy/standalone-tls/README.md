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
mkdir -p data backups && sudo chown -R 1000:1000 data backups
docker compose up -d
```

The `chown` matters on a real Linux host: the container runs as a non-root
uid-1000 user, but if `data`/`backups` don't already exist, Docker creates
them owned by **root** the moment `docker compose up` tries to bind-mount
them — and the app then fails to start at all (`unable to open database
file`). Creating the folders and fixing ownership yourself first avoids
this. (Not needed on Windows/Docker Desktop, whose bind-mount layer doesn't
enforce uid ownership the same way — this is a real-Linux-host-only step.)

Browse to `https://<host>/` — you'll get a certificate warning (expected,
it's self-signed); accept it to continue. The phone app can point at the same
`https://` URL with no cleartext warning, since the connection is genuinely
encrypted even though the cert isn't from a public CA.

To trust the cert instead of clicking through the warning every time, install
`certs/cert.pem` as a trusted root on each client device.

If you provide your own `certs/key.pem` instead of using `generate-cert.sh`
(e.g. a cert from an internal CA), make sure it's readable by the `proxy`
container — `chmod 644 certs/key.pem` — since `generate-cert.sh` already
does this for you but a manually-placed key may not have it. There's nothing
in `certs/` more sensitive than the rest of this deployment folder, so
matching `cert.pem`'s permissions is fine.

`app` runs the published image (`ghcr.io/sjefferson99/simple-activity-tracker-server:latest`,
the same one CI pushes on every merge to `main`) — to update to the latest
version later: `docker compose pull app && docker compose up -d`.

## Updating and rolling back

`app` tracks `:latest`, so `docker compose pull app && docker compose up -d`
always picks up the newest build from `main`. `docker compose ps` should show
both services `healthy` within a few seconds; if not, `docker compose logs app`
first (migrations run at startup and fail loudly on a real problem).

To roll back, every merge to `main` also gets an immutable `sha-<commit>` tag
on the same image (see `.github/workflows/container.yml`) — find the last
known-good commit (`git log --oneline server/`), then:

```bash
docker pull ghcr.io/sjefferson99/simple-activity-tracker-server:sha-<commit>
docker compose stop app
docker run --rm --env-file .env -v ./data:/data \
  ghcr.io/sjefferson99/simple-activity-tracker-server:sha-<commit> --help  # sanity check the tag exists/pulls
```

then temporarily point `app.image` in `docker-compose.yml` at that
`sha-<commit>` tag and `docker compose up -d` — switch it back to `:latest`
once you're ready to move forward again. There's no automatic downgrade path
for the database itself (migrations only run forward); rolling back the image
after a migration has already run against your data is not supported by this
setup — restore from a backup instead if that ever happens (see "Backups and
migration safety" below).

## Secrets

By default `SR_SECRET_KEY` and `SR_ADMIN_PASSWORD` live in `.env`, which
Compose injects as plain environment variables — visible to anyone who can
run `docker inspect` on the container. For a shared/multi-user host, prefer
Docker Compose's `secrets:` block instead, which mounts each value as a file
under `/run/secrets/` and keeps it out of the environment entirely:

```yaml
services:
  app:
    secrets:
      - SR_SECRET_KEY
      - SR_ADMIN_PASSWORD
    # ...

secrets:
  SR_SECRET_KEY:
    file: ./secrets/secret_key.txt        # gitignored — contains the raw value, no quotes/newline
  SR_ADMIN_PASSWORD:
    file: ./secrets/admin_password.txt
```

The mounted filename must match the setting's env var name exactly (e.g.
`/run/secrets/SR_SECRET_KEY`) — the app checks `/run/secrets/` automatically
for every setting, not just these two, and an env var of the same name always
wins if both are set. `SR_ADMIN_PASSWORD` only does anything on the very
first startup with an empty database (see "First-boot admin bootstrap" in
`.env.example`) — the app logs a warning at startup if it's still set once
users already exist, as a nudge to remove it.

**Rotating `SR_SECRET_KEY`**: generate a new one
(`python -c "import secrets; print(secrets.token_urlsafe(32))"`), update it
wherever it's stored (`.env` or the secrets file), then `docker compose up -d`.
It's only used to sign the browser's session cookie, so every signed-in
browser gets logged out and has to sign in again — phone-app device tokens
are unaffected (they're opaque, independently generated values checked
against the database, not signed with this key) and keep working. Nothing
else breaks: no data is re-encrypted or affected, since the key never
encrypts anything at rest.

## Backups and migration safety

`run` (the app's default startup command) automatically backs up the
database and GPX blobs to `./backups/` before applying any pending
migrations, then migrates and starts. This is on by default
(`SR_BACKUP_BEFORE_MIGRATE=true`); disable it with
`SR_BACKUP_BEFORE_MIGRATE=false` if you'd rather manage backups entirely
yourself.

To take a manual backup at any time (the container doesn't need to be
stopped — it uses SQLite's `VACUUM INTO`, a consistent snapshot even against
a live WAL-mode database):

```bash
docker compose run --rm app simple-activity-tracker-server backup /backups
```

Each run creates a new timestamped subdirectory under `./backups/`
(`backup-<UTC-timestamp>/`) containing the database file and a copy of the
`gpx/` blob tree — self-contained, so copying that one subdirectory
elsewhere (another disk, off-site storage) is a complete backup.

**To restore:**

```bash
docker compose stop app
rm -rf data/*                                  # or move aside if you want to keep it around
cp -r backups/backup-<timestamp>/simple_activity_tracker.db data/
cp -r backups/backup-<timestamp>/gpx data/
docker compose up -d
```

There's no automatic downgrade path for the database itself (migrations only
run forward) — restoring a backup taken before a migration ran is the way to
undo one if it caused a problem.

**`SR_AUTO_MIGRATE`** (default `true`) controls whether `run` applies pending
migrations automatically at startup. Set to `false` for a deployment where
you'd rather apply migrations deliberately and out-of-band — with it false,
`run` refuses to start at all if the database isn't already at the latest
migration:

```bash
docker compose run --rm app simple-activity-tracker-server migrate
docker compose up -d
```

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
