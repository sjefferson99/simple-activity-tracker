# Split library plan: folders, template repos, import/export (issue #143)

Status: **implemented on branch `server-143-split-library`, awaiting sign-off.**

Builds on saved split configs ([SPLIT-CONFIGS-PLAN.md](SPLIT-CONFIGS-PLAN.md),
#126), repeat groups (#233) and Duplicate (#231). Lays the ground for
programmes (#230).

## 0. Decisions (owner, 2026-11-24)

| # | Decision | Choice |
|---|----------|--------|
| L1 | Splits page | Shows the user's configs and subscribed templates **grouped by folder**. A "Library" link opens the management page. |
| L2 | Library page (web **and** phone) | Lists split repos ("sources"), turns each source's folders on and off, adds/edits/removes repos, syncs, and imports/exports the user's own configs. |
| L3 | Who adds repos | **Each user** manages their own sources. The project's own repo (`splits/` on `main`) is subscribed for everyone by default (`SR_SPLIT_LIBRARY_DEFAULT_REPO`; empty turns it off). The default source can be switched off, not removed. |
| L4 | Fetching | **HTTPS archive download** (tarball) from GitHub, GitLab or Gitea/Forgejo. No git binary, no new server dependency. An optional access token covers private repos. |
| L5 | Templates are read-only | Template rows can't be edited, renamed or deleted, by web or API. They offer **Copy**, which is Duplicate (#231) into the user's own configs. |
| L6 | Identity | Every config has a `uid` (existing rows are backfilled with their id). Repo files and export files carry it. Sync matches templates by `uid`, so a renamed or moved file updates in place; import matches the user's own configs by `uid`. |
| L7 | Hiding | Per **folder** (and per source). A hidden folder's templates disappear from the web list and from `GET /split-configs`, so every app, old or new, stops offering them on its next refresh. |
| L8 | Own configs in folders | A config has an optional `folder` (free text). Names stay unique per user across folders (O6 unchanged). Templates don't take part in name uniqueness, so an old app's "save as" can never overwrite one. |
| L9 | Couch to 5K | Built from the NHS 9-week plan: 5 min walk warm-up and cool-down, walk at 10:00/km, run at 7:30/km, one file per run. |

## 1. File formats

**One config** (a repo file, or "Export" of a single config):

```json
{
  "format": "sat-split-config",
  "version": 1,
  "uid": "8d0c…",
  "name": "Week 1, run 1",
  "plan": { "split_type": "time_min", "split_value": 1, "custom_splits": [[300, 1.667]], "targets_as": "pace", "layout": [...] }
}
```

`plan` is exactly `SplitPlanIn`, validated the same way as an API write. A repo
file's folder comes from its path, so a `folder` key there is ignored.

**Bundle** (export of many configs, import accepts either form):

```json
{ "format": "sat-split-configs", "version": 1,
  "configs": [ { "uid": "…", "name": "…", "folder": "Intervals", "plan": {…} } ] }
```

**Repo layout:** `<path>/<folder>/<file>.json`, `path` defaulting to `splits`.
Files straight under `<path>` have no folder. An optional
`<path>/<folder>/_folder.json` (`{"name": "Couch to 5K", "description": "…"}`)
gives the folder its display name; otherwise the directory name is used. A
`uid` is optional in a repo file; without one, it's derived from the source and
file path (uuid5), which is stable until the file moves.

## 2. Server

### 2.1 Data model (one migration)

- `split_configs` gains `uid` (String 36, backfilled = `id`), `folder`
  (String 200, nullable), `source_id` (FK → `split_sources`, nullable; set =
  template). The `(user_id, name)` unique constraint becomes a partial unique
  index on `source_id IS NULL`; templates get a partial unique index on
  `(source_id, uid)`. Own configs get a unique `(user_id, uid)` partial index.
- `split_sources`: id, user_id, name, url, host_kind (`github`/`gitlab`/`gitea`),
  ref, path, token (nullable, never returned by any API or page), enabled,
  is_default, last_synced_at, last_commit, last_error, warnings (JSON list),
  created_at.
- `split_source_folders`: id, source_id, folder (path), display_name,
  description, enabled (new folders default on).
- User deletion removes all three (cascades.py). This also fixes deleting a
  user who has split configs, which used to fail on the FK.

### 2.2 Fetch and sync (`app/split_library/`)

- Archive URLs: GitHub `api.github.com/repos/o/r/tarball/<ref>`
  (`Authorization: Bearer`), GitLab `/api/v4/projects/<o%2Fr>/repository/archive.tar.gz?sha=<ref>`
  (`PRIVATE-TOKEN`), Gitea/Forgejo `/api/v1/repos/o/r/archive/<ref>.tar.gz`
  (`Authorization: token`). Host kind is auto-detected for github.com and
  gitlab.com, otherwise chosen by the user.
- **SSRF guards:** https only, no proxy. On every redirect hop, every address
  the host resolves to must be public, checked *before* connecting (so a
  closed internal port and an open one give the same answer: no port-scan
  oracle), and the connected peer is checked again before the TLS handshake
  (DNS rebinding). The token is dropped when a redirect changes host.
  `SR_SPLIT_SOURCES_ALLOW_PRIVATE_HOSTS=true` opts in to a LAN Gitea.
  `SR_SPLIT_SOURCES_ALLOW_USER_REPOS=false` limits users to the default repo.
- **Limits:** 20 s timeout, 10 MB download, 64 MB scanned (decompressed) from the archive, 60 s for the whole download,
  500 config files, 64 KB per file. The tarball is read in memory with
  `tarfile` in streaming mode; only regular `.json` files under `path` are
  read, nothing is written to disk.
- **Sync:** parse every file (an invalid one is skipped and listed in
  `warnings`, it never fails the sync), upsert templates by `uid`, delete
  templates whose file is gone, add/update/remove folder rows. One sync per
  source at a time (in-process lock). An archive fetched in the last 10 min is
  reused, so every user's default source costs one download.
- **When:** "Sync now" (web/phone); automatically in the background when a
  source is older than `SR_SPLIT_SOURCES_SYNC_HOURS` (24) and the user lists
  configs; inline the first time the web splits page creates the default
  source, so a new user sees templates straight away.

### 2.3 API (level 4, additive)

- `SplitConfigOut` gains `uid`, `folder`, `read_only`, `source` (`{id, name}` or
  null), `folder_name` (display). Create/patch take an optional `folder`.
- `GET /split-configs` returns own configs plus templates from enabled
  folders of enabled sources. PATCH/DELETE of a template → **403
  `read_only`**. POST with `overwrite` only ever matches own configs.
- `GET /split-configs/export[?folder=…][&id=…]` → bundle of own configs (an
  `id` may name a template too, for sharing one).
- `POST /split-configs/import` (bundle or single) → `{created, updated, renamed, errors}`.
  Same uid → replaces that config. New uid with a taken name → "Name (2)".
- `/split-sources`: `GET` (sources with folders, counts, sync status,
  `has_token`), `POST` (url, host_kind?, ref?, path?, name?, token?), `PATCH
  /{id}` (name, ref, path, token, clear_token, enabled), `DELETE /{id}` (not the
  default; removes its templates), `POST /{id}/sync`, `PATCH
  /{id}/folders/{folder_id}` (`enabled`).

### 2.4 Web

- `/split-configs`: one card per folder (own folders first, then each source's
  enabled folders), templates marked with their source and offering
  View/Copy/Export. Own configs keep Edit/Duplicate/Delete and gain Export.
- `/split-configs/library`: sources with folder switches, sync status and
  warnings, Sync now, add/edit/remove repo, import (file upload) and export
  (all or one folder).
- Editor: a Folder field with a datalist of existing folders.

## 3. Mobile (gated on server API level ≥ 4)

- Saved-config picker groups by folder; templates show a "template" badge and
  only offer Load. Older servers: flat list, unchanged.
- **Library screen** from the Splits screen: the same sources/folders/sync/add
  repo controls as the web, plus import (file picker) and export (saved to
  Downloads). Hidden for older servers with "needs a newer server".
- Save-as gets an optional folder on level 4+.

## 4. Couch to 5K content (`splits/couch-to-5k/`)

27 files, `week-N-run-M.json`, time-based custom splits, warm-up and cool-down
walks of 5 min, walk 10:00/km (1.667 m/s), run 7:30/km (2.222 m/s), repeats as
layout blocks. Weeks 1–4 and 7–9 repeat the same run three times; weeks 5 and 6
have three different runs.

## 5. Verification

Server suite + openapi diff + Snyk; fetch tests against a stub fetcher (no
network in tests) plus real-container checks that the default repo syncs from
GitHub once the branch is pushed (until then, a local source via
`SR_SPLIT_SOURCES_ALLOW_PRIVATE_HOSTS`). Mobile: analyze, tests, on-device
picker grouping and the Library screen against level 3 and level 4 servers.
