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
the newest release; see "Image tags" below to follow `main` or pin a version
instead) — to update to the latest release later:
`docker compose pull app && docker compose up -d`.

## Image tags

`docker-compose.yml` runs `:${SR_IMAGE_TAG:-latest}`, so you choose the tag in
`.env` without editing the compose file:

| `SR_IMAGE_TAG` | You get |
|---|---|
| unset or `latest` | the newest release (recommended) |
| `1.3` | the newest patch release in the 1.3 line |
| `1.3.0` | exactly that release; never changes |
| `edge` | every merge to `main`: unreleased code, for testing |

After changing it: `docker compose pull app && docker compose up -d`.

**Before switching to `edge`, take a backup** (see "Backups and migration
safety"), and copy it somewhere outside `backups/` if you'll be on `edge` for a
while, since later automatic backups rotate older ones out. An `edge` build can
migrate your database ahead of the newest release. Switching back to `latest`
(or to an older pinned version) then puts an older image in front of a newer
database, and the app refuses to start, saying so; it changes nothing and
leaves your backups alone. To leave `edge`, either stay on it until the next
release catches up (then unset `SR_IMAGE_TAG`), or restore the backup you took
before switching and then change the tag.

Until v1.3.0, `:latest` followed `main`. If you want to keep following `main`
after upgrading, set `SR_IMAGE_TAG=edge`.

## Updating and rolling back

`docker compose pull app && docker compose up -d` picks up the newest image
for your tag: the newest release on `latest`, the newest `main` build on
`edge`, nothing new on a pinned `X.Y.Z`. `docker compose ps` should show
both services `healthy` within about 30 seconds; if not, `docker compose logs app`
first (migrations run at startup and fail loudly on a real problem).

An update that includes a database migration first writes a backup (see
"Backups and migration safety"), then migrates, and only then starts serving.
On a large instance that can take a few minutes. Meanwhile `app` shows
`(health: starting)`, not `(unhealthy)`, because the image's healthcheck
allows up to 10 minutes for startup. `docker compose up -d` waits for it before
starting `proxy`.

When an update changes what the server derives from a GPX (it bumps
`ANALYSIS_VERSION` in `server/app/analysis/v1.py`; the release notes / PR will
say so), the app reanalyses the affected activities **in the background after
it starts serving** (`SR_AUTO_REANALYZE`, below). The site is up straight away,
and each activity shows its previous analysis until its turn comes. On a few
hundred activities this takes a few minutes. The logs show progress:

```
... INFO app.reanalysis Reanalyzing 344 activity(ies) at analysis_version=14...
... INFO app.reanalysis   <activity id>: done
... INFO app.reanalysis Reanalysis finished: 344 done, 0 failed, 0 skipped, 0 errors.
```

Each activity is saved as soon as it's done. If the container is stopped or
restarted partway, the next start carries on with the ones left. To run it by
hand instead (e.g. with `SR_AUTO_REANALYZE=false`):

```bash
docker compose exec app simple-activity-tracker-server reanalyze --all
```

It only touches activities whose stored version is older than the current one,
so it is safe to run after every update.

To roll back, pin the previous release (`SR_IMAGE_TAG=1.2.6`, say) or, on
`edge`, a specific build: every build also gets an immutable
`sha-<short-commit>` tag (see `.github/workflows/container.yml`). For the
latter, find the last known-good commit (`git log --oneline server/`, which
prints the same short SHA the tag uses), then:

```bash
docker pull ghcr.io/sjefferson99/simple-activity-tracker-server:sha-<short-commit>
docker compose stop app
docker run --rm --env-file .env -v ./data:/data \
  ghcr.io/sjefferson99/simple-activity-tracker-server:sha-<short-commit> --help  # sanity check the tag exists/pulls
```

then temporarily set `SR_IMAGE_TAG=sha-<short-commit>` in `.env` and
`docker compose up -d` — set it back (or unset it) once you're ready to move
forward again. There's no automatic
downgrade path for the database itself (migrations only run forward); rolling
back the image after a migration has already run against your data is not
supported by this setup — restore from a backup instead if that ever happens
(see "Backups and migration safety" below).

A release is the safer thing to pin to than a commit SHA: `X.Y.Z` never moves,
and `X.Y` follows only patch releases in that line.

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
migrations, then migrates and starts. It only does this when there is a
migration to apply: restarting an up-to-date stack takes no backup. This is
on by default (`SR_BACKUP_BEFORE_MIGRATE=true`); disable it with
`SR_BACKUP_BEFORE_MIGRATE=false` if you'd rather manage backups entirely
yourself.

**Retention:** after each backup (automatic or manual), the oldest
`backup-<timestamp>/` directories beyond `SR_BACKUP_KEEP` (default `5`) are
deleted. `SR_BACKUP_KEEP=0` keeps everything. Only directories matching the
app's own `backup-<timestamp>` naming are ever removed; anything else you put
in `./backups/` is left alone. If you copy backups off-site, make sure that
runs often enough that rotation doesn't remove one before it's copied.

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

A manual backup applies the same retention; pass `--keep N` to override
`SR_BACKUP_KEEP` for that run (`--keep 0` keeps everything).

**Cleaning up an older deployment:** versions before this change took a full
backup on *every* start and never removed any, so `./backups/` may hold
hundreds of copies. After upgrading, the next backup prunes to
`SR_BACKUP_KEEP` automatically, but an up-to-date stack may not take one for
a long time. To clean up now, take a manual backup (this also prunes):

```bash
du -sh backups                       # before
docker compose run --rm app simple-activity-tracker-server backup /backups
du -sh backups                       # after
```

Entries not named `backup-<timestamp>` (for example `20260903_181135`, from
the very first backup code) are never pruned automatically. Check them and
remove them by hand if you don't need them (`sudo` may be needed, as the
container writes as uid 1000).

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

**An older image against a newer database:** if a newer version has already
migrated the database (for example after rolling the image back), `run`
refuses to start with a message saying so. It writes no backup and prunes
nothing, so the backups you'd restore from are left alone however often the
container restarts. Go back to the newer image, or restore a backup taken
before it migrated (above).

**`SR_AUTO_MIGRATE`** (default `true`) controls whether `run` applies pending
migrations automatically at startup. Set to `false` for a deployment where
you'd rather apply migrations deliberately and out-of-band — with it false,
`run` refuses to start at all if the database isn't already at the latest
migration:

```bash
docker compose run --rm app simple-activity-tracker-server migrate
docker compose up -d
```

**`SR_AUTO_REANALYZE`** (default `true`) controls whether `run` also reruns
the analyzer against every activity whose stored analysis predates the
current analyzer version, in the background once the app is serving. It's
the same work `simple-activity-tracker-server reanalyze --all` does by hand,
and a fast no-op once nothing is stale. This is what applies
an analyzer bugfix or algorithm change (e.g. corrected GPS-jump/accuracy
filtering) to activities uploaded before the upgrade, automatically, without
the phone re-uploading anything. Set to `false` to leave stored analyses
as-is until `reanalyze --all` is run out-of-band:

```bash
docker compose run --rm app simple-activity-tracker-server reanalyze --all
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

### Contract any reverse proxy must satisfy

Whatever you put in front of `app`, it must:

- **Forward `Host`, `X-Forwarded-Proto`, and `X-Forwarded-For`.** The app trusts
  these only from `SR_TRUSTED_PROXIES` and uses them to build absolute URLs,
  decide whether a request is "real HTTPS" (for `Secure` cookies and HSTS —
  see S5 in docs/SERVER-PRODUCTION-PLAN.md), and log/rate-limit by client IP.
  Without them, every request looks like plain HTTP from the proxy's own IP.
- **Set `SR_TRUSTED_PROXIES` to the proxy's exact subnet, not a broad default.**
  The bundled `nginx.conf` setup uses the Docker default bridge range
  (`172.16.0.0/12`) because it's the only thing on that network, but that
  range trusts every container on the host, not just your proxy — narrow it
  (`docker network inspect <network>` to find the real subnet) if your proxy
  shares a network with anything else.
- **Allow a request body of at least `SR_MAX_GPX_BYTES`** (default 20 MB) —
  most reverse proxies cap request size well below that by default (e.g.
  nginx's `client_max_body_size`, Traefik's none-by-default-but-check-your-
  middleware, Caddy's none-by-default). A cap set lower than this silently
  turns every large GPX upload into a proxy-level 413 the app never sees.
- **Never rely on the app to redirect `http://` to `https://` itself** — it
  doesn't, on purpose (TLS termination and any http→https redirect are the
  proxy's job, per docs/WEB-PLAN.md §5.6). If you want that redirect, your
  proxy has to do it, the way `nginx.conf` does here.
- **No websocket support needed.** Nothing in this app uses WebSockets — the
  live map/chart pages poll or load data once, they don't hold an open
  connection — so there's nothing extra to configure for that.

### Caddyfile example

A minimal `Caddyfile` doing the same job as this repo's bundled nginx config
(HTTPS termination, forwarding the required headers, no size cap below the
app's own limit):

```
your.domain.example {
	reverse_proxy app:8000 {
		header_up X-Forwarded-Proto {scheme}
		header_up X-Forwarded-For {remote_host}
		header_up Host {host}
	}
	request_body {
		max_size 25MB
	}
}
```

Caddy handles ACME certificate provisioning and the http→https redirect
automatically for a real domain name — there's no self-signed-cert step to
replicate. Set `SR_TRUSTED_PROXIES` to wherever this Caddy instance's traffic
actually originates from (its container's subnet, or `127.0.0.1` if it runs
on the same host outside Docker).
