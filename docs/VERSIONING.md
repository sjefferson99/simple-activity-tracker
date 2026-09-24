# Versioning and app ↔ server compatibility

**Read this before changing anything the mobile app sends to, or reads from, the
server** — any `/api/v1` request or response, and any field in the upload
payload. Issue #141 introduced it after a dev build of the app failed to upload
to an older server, because the app sent fields that server had never heard of.

The phone and the server are updated independently: an APK install on one side,
a `docker pull` on the other. Users will routinely run a newer app against an
older server, and the reverse. **Both directions must keep working.**

## 1. The two numbers

| | What it is | Who changes it | Where it lives |
|---|---|---|---|
| **Release version** (`1.3.0`) | Identifies a build, for people. One number shared by the app and the server | Cutting a `vX.Y.Z` release tag. Never edited by hand | The git tag. CI injects it into both builds |
| **API level** (`1`, `2`, …) | The version of the `/api/v1` contract, for code. The app decides what it may send or call from the server's API level, never from its release version | The PR that changes the API, in the same commit as the change | `server/app/api_compat.py` and `mobile/lib/core/version/api_compat.dart` (kept equal by a test) |

The release version is for display only. **Never compare release versions in
code to decide compatibility.** A PR can't know the release number it will ship
in, but it always knows whether it changed the API.

### Release version, where it comes from

- **Tag builds** (`v1.3.0`): `mobile-release.yml` builds the APK with
  `--build-name=1.3.0`. `container.yml` passes `APP_VERSION=1.3.0` into the
  image (`SAT_BUILD_VERSION` env var, read by `server/app/version.py`).
- **`main` builds of the server image** (`:latest`) report `git describe`-style
  versions: `1.3.0+4.gabc1234` means 4 commits after `1.3.0`, at commit
  `abc1234`.
- **Local builds** report `dev`. For the app, that's any build whose pubspec
  version is still the `0.0.0` placeholder. For the server, it's any image
  built without the build arg.
- `pubspec.yaml`'s `version:` and `pyproject.toml`'s `version` are placeholders.
  Don't bump them; the tag is the only source.

### Where it's shown

- **Mobile:** Settings → "About": the app version and its API level. When
  signed in, it also shows the server's version and API level, plus a
  compatibility line (§4).
- **Web:** the page footer, for signed-in users only. An anonymous visitor
  still sees no version, per S7 in docs/SERVER-PRODUCTION-PLAN.md.
- **API:** `GET /api/v1/server-info` (requires sign-in) returns
  `{version, api_level, min_app_api_level}`. Servers from before this existed
  (≤ v1.2.4) return 404, and the app treats that as **API level 0**.
- Every app request carries `X-App-Version` and `X-App-Api-Level` headers.
  Nothing reads them yet. They exist so a future server can tell old apps
  apart, which can't be added to app builds that are already installed.

## 2. API levels

| Level | Servers | What the contract is |
|---|---|---|
| 0 | v1.0.0 – v1.2.4 (no `/server-info`) | Upload accepts only the v1.0.0 fields: no `max_speed_mps`, no `elevation_gain_meters`, no split `target_speed_mps`. `walking` and `/split-configs` exist only on v1.2.4, so the app must cope with them being missing (§3). Unknown fields → **422** |
| 1 | from #141 | Everything v1.2.4 accepts, plus `/server-info`. **Unknown request fields are ignored, not rejected** |

Add a row here whenever `API_LEVEL` goes up.

### Server constants (`server/app/api_compat.py`)

- **`API_LEVEL`**: bump it in any PR that changes `server/openapi.json`'s
  `paths` or `components`. That includes a new endpoint, a new request field, a
  new enum value, a new response field, and any removal. Additive changes still
  count, because the app gates on them. It's also written into `openapi.json`
  as `info.version`.
- **`MIN_APP_API_LEVEL`**: the oldest app API level this server still fully
  supports. Bump it **only** when the server removes or changes something an
  older app relies on, which should be very rare (§5). It's currently 0: every
  app ever released still works.

### App constants (`mobile/lib/core/version/api_compat.dart`)

- **`kAppApiLevel`**: the API level this app was built against. It always equals
  the server's `API_LEVEL` in the same commit; a mobile test reads
  `server/app/api_compat.py` and fails if they differ.
- **`kMinServerApiLevel`**: the oldest server API level this app still supports.
  Bump it **only** when you deliberately drop support for older servers. It's
  currently 0: the app works with every server ever released.

### CI enforcement (`server.yml`, `server/scripts/check_api_level.py`)

On every PR, CI compares `server/openapi.json` with the version on `main`:

1. If `paths`/`components` changed and `API_LEVEL` didn't go up → **fail**.
2. If oasdiff reports a **breaking** change and `MIN_APP_API_LEVEL` didn't go
   up → **fail**. The better fix is usually to make the change non-breaking
   (§5), not to bump the minimum.
3. `API_LEVEL` never goes down, and `MIN_APP_API_LEVEL ≤ API_LEVEL`.

The app side isn't checked by CI beyond the level-equality test. The rules in §3
are what keep it safe, and the contract tests (§6) catch the most common
mistake.

## 3. Rules for the mobile app: never break on an older server

1. **Shape every request to the server's level.** A request field added at
   level N is only sent when `serverApiLevel >= N`. The upload payload is built
   in one place: `buildUploadSummaryJson()` in
   `mobile/lib/core/api/upload_payload.dart`. `RunSummary.toJson()` stays the
   full local-sidecar format and is **never** sent to the server directly.
2. **Gate new endpoints on the level.** Only call an endpoint added at level N
   when `serverApiLevel >= N`. Otherwise hide or disable the feature with
   "needs a newer server" wording. Endpoints that exist on some level-0 servers
   but not others (`/split-configs`) must treat **404** as "this server doesn't
   support it", not as an error.
3. **Read responses tolerantly.** Any response field that isn't present at
   level 0 is parsed as optional with a sensible default (`as T?` / `?? x`),
   never with a cast that throws. Unknown enum values from the server (a new
   activity type, say) must not throw. Fall back to a generic display.
   Free-form maps (`analysis.result`) are read only through
   `core/api/tolerant_json.dart` (`readDouble`, `readMapList`, …), which
   return null for a missing *or* wrongly typed value. A malformed list item
   is skipped, not rendered.
4. **Enum values are fields too.** A new value the app sends (like `walking`)
   is gated like a new field where possible. Where it can't be (the activity
   really is a walk), the resulting 400 becomes a clear, non-retryable failure
   that tells the user the server may be older than the app. It's retried
   automatically once the server reports a higher API level.
5. **The local record is never trimmed.** Shaping only affects what goes over
   the wire. The sidecar keeps every field, so once the server is upgraded the
   data is still there.
6. **When compatibility is out of range** (`kAppApiLevel < min_app_api_level`,
   or server `api_level < kMinServerApiLevel`), uploads pause (records stay
   pending, nothing is lost) and Settings shows which side to update.

## 4. What the user sees

| Situation | Settings shows |
|---|---|
| Same release version | `App 1.3.0 · Server 1.3.0` |
| Different versions, compatible | Both versions, plus "Matching versions are recommended." as a neutral note, not a warning |
| Server predates `/server-info` | "Server: v1.2.4 or older", plus a neutral note that some newer features need the server updated |
| App too old for the server | Warning: "This app is too old for the server. Update the app." Uploads paused |
| Server too old for the app | Warning: "The server is too old for this app. Update the server." Uploads paused |

## 5. Rules for the server: never break an older app

1. **Additive only.** New request fields are optional with a default. Never
   make an existing optional field required, never remove or rename a field or
   endpoint, and never narrow an accepted value (enum, range, length) that a
   released app might send.
2. **Ignore unknown request fields** (`extra="ignore"` on every request model
   in `app/api/v1/schemas.py`), never `forbid`. That's what makes a *future*
   app safe against *this* server.
3. **Responses only grow.** Never remove a response field or change its type;
   released apps may cast it.
4. **`analysis.result` follows the same rule, but CI's API-level guard can't
   see it** (it's `dict[str, Any]` in openapi.json). Every field an app reads is
   listed in `contract/analysis-result/app-reads.json` with its type. Released
   apps up to v1.2.4 hard-cast some of these (split `index` as an int, a best
   effort's `distance_meters`), so a rename or type change crashes their
   activity screen. Only ever add entries to that file. A new analyzer field
   the app starts reading goes in as `|optional`, because older servers never
   produce it.
5. **GPX `sat:` extensions are a contract too.** Never change an existing
   extension's value format (`split_plan`'s `size@target;…`, `split_value` as a
   whole number, the `split_type` names). Older servers parse them as they
   are. New meaning gets a new extension name, which older servers ignore
   (they have always ignored unknown extensions; verified against the v1.0.0
   parser).
6. If something truly has to break, bump `MIN_APP_API_LEVEL`, and say so in the
   release notes: older apps will show "update the app".

## 6. Contract tests

`contract/upload-summary/` holds real upload payloads:

- `legacy-app-v1.0.0.json` and `legacy-app-v1.2.4.json`: what those released
  apps actually send. **Frozen.** The server must keep accepting them until
  `MIN_APP_API_LEVEL` goes above 0.
- `api-level-N.json`: what the current app sends to a level-N server. Mobile's
  `test/core/api/upload_payload_test.dart` compares against these (golden
  files). After a deliberate payload change, regenerate them with
  `flutter test --dart-define=UPDATE_CONTRACT=true test/core/api/upload_payload_test.dart`.
  The level-0 payload is also checked against the frozen v1.0.0 field set.

`server/tests/test_api_contract.py` uploads every file in that directory and
requires a `201`. For `api-level-N.json` where N ≤ the current `API_LEVEL`, it
also requires that **no field was silently ignored**. That's how the server
proves it understands everything the current app sends, even though it would
also accept payloads with fields it doesn't know.

Two more contracts live outside openapi.json, so they get their own tests:

- **`contract/analysis-result/app-reads.json`**: every `analysis.result` field
  an app reads, with its type (§5.4). `server/tests/test_analysis_contract.py`
  uploads a real 3 km run and checks the analyzer's actual output against it,
  and `test_gpx_contract.py` does the same for each contract GPX.
- **`contract/gpx/<name>.gpx` + `<name>.expected.json`**: GPX written by the
  app's real `RunGpxLog` (golden files, `test/core/files/gpx_contract_test.dart`,
  regenerated the same way as the upload payloads), plus what the app *means*
  by each: split plan, targets, per-point accuracy and speed.
  `server/tests/test_gpx_contract.py` requires the server's parser to extract
  exactly that.

### Known limits with level-0 servers (≤ v1.2.4)

Level 0 covers several releases the app can't tell apart, so a few things are
handled at the point of failure rather than gated in advance:

- **`walking` activities** are rejected by servers before v1.2.4. The upload
  fails with an "older than this app" message and retries automatically once
  the server reports level 1 or higher.
- **Saved split configs** don't exist before v1.2.4. The 404 is shown as "this
  server is too old for saved configs".
- **Max speed, elevation gain and split targets** are left out of the upload
  summary for every level-0 server, including v1.2.4, which could accept them.
  The GPX still carries the split plan and targets.

## 7. Checklist for a PR that touches the API

- [ ] Change is additive (§5), or `MIN_APP_API_LEVEL` is bumped with a reason.
- [ ] `API_LEVEL` bumped in `server/app/api_compat.py`, and `kAppApiLevel` in the app.
- [ ] `server/openapi.json` regenerated.
- [ ] New row in §2's level table.
- [ ] App gates the new field/endpoint on `serverApiLevel >= N` (§3). New
      response fields are parsed as optional.
- [ ] `contract/upload-summary/api-level-N.json` added if the upload payload changed.
- [ ] Analyzer change: every field in `contract/analysis-result/app-reads.json`
      still present with the same type. New field the app reads: added there as
      `|optional`, and read through `tolerant_json.dart`.
- [ ] GPX change: only *new* `sat:` extensions. Goldens in `contract/gpx/`
      regenerated and `.expected.json` updated.
- [ ] Tested the app against a server at the **previous** level (or a mocked
      level) as well as the current one.
