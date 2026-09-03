# Mobile app — code-quality & security review and action plan

**Scope:** the Flutter app in `mobile/` (Android and iOS), reviewed 2026-09-03 at the MVP
milestone. **Target state is "good code quality for internal testing"** — not app-store
release. Items that only matter for a store release are collected in §6 so they aren't
mixed in with the work to do now.

**How to use this document (for the implementing agent):**

- Read [PLAN.md](PLAN.md) §3 and §7 (architecture rules, working agreements),
  [WEB-PLAN.md](WEB-PLAN.md) §6 (mobile sync design) and the "Current status" section of
  [../CLAUDE.md](../CLAUDE.md) first — especially its toolchain notes; several build
  gotchas there (Gradle daemon locks, `flutter install` not rebuilding, the compileSdk
  patches in `android/build.gradle.kts`) will bite otherwise.
- Working agreements still apply: `flutter analyze` and `flutter test` clean (run from
  `mobile/`), `core/units` and `domain/` stay pure Dart, GPS only via `LocationService`,
  Snyk code scan clean on new code, **prompt before adding any dependency or installing
  anything**, and **ask before every `git commit`**.
- Items are grouped by workstream and ordered by priority. **B-items are real bugs found
  in review — do them first.** Each has a `Do` and a `Verify`.
- Device verification: use the physical Samsung S10 for anything touching GPS, upload or
  background behaviour; take a screenshot (`adb exec-out screencap -p > file.png`) rather
  than trusting a successful install.

Review tooling: Snyk code scan on `mobile/lib` clean (0 issues); `flutter pub outdated`
shows all direct dependencies at their latest versions (only transitive/dev packages lag).
Test suite at review: 112 tests in 14 files, all pure-Dart/`MockClient`/fake-based; no
widget tests and no `LiveRunController` tests.

---

## 1. What's already good (keep it)

- Clean layering: geolocator types stay inside `core/location`; `domain/` is pure Dart
  and well tested (outlier rejection, re-anchoring, split interpolation).
- Crash-safe GPX and sidecar writes (temp + atomic rename, chained flushes).
- Typed `ApiException` hierarchy, retryable-vs-permanent split, single-flight sync queue
  with backoff, idempotent upload keyed on `client_activity_id`.
- Credentials in `flutter_secure_storage`; password never persisted; 401 signs the device
  out without losing the queue.
- Trust-on-first-use certificate pinning instead of a "disable TLS validation" switch,
  with the decision logic factored into a pure, tested function.
- Sign-in errors stay inline in the form (the `AsyncError`-wipes-the-form bug is fixed).

---

## 2. Workstream B — Bugs (P0)

### B1 — A record can get stuck in `uploading` forever

`FileRunStore.listPendingOrRetryable()` returns only `pending` and `failed(retryable)`;
`SyncService.retryNow()` resets only `failed`. `_attemptUpload` writes
`SyncStatusUploading` to disk *before* the call, so anything that prevents it from
writing a follow-up status leaves the sidecar in `uploading`, which no code path ever
picks up again:

- the app is killed (or the OS kills it) mid-upload — the W3 acceptance test "kill the
  app mid-upload" passed only because the kill happened while the record was still
  `pending`;
- `uploadRun` throws something that is **not** an `ApiException`: `FormatException` from
  `_decodeJson` (a captive-portal or proxy page returning HTTP 200 HTML), `TypeError`
  from a bare `as` cast in `RunDto.fromJson` if a field shape changes, or any
  `FileSystemException` opening the GPX. The `on ApiException` handlers don't catch these;
  the error propagates out of `_drainQueue`, `_inFlightPass` is cleared by
  `whenComplete`, and the record is orphaned.

The same unmapped `FormatException` reaches the sign-in form as a raw
`FormatException: Unexpected character…` message.

- Where: `lib/core/sync/sync_service.dart`, `lib/core/sync/file_run_store.dart`,
  `lib/core/api/http_api_client.dart`, `lib/core/api/dto/*.dart`.
- Do:
  1. In `HttpApiClient._send`/`_decodeJson`, catch `FormatException` and `TypeError` from
     decoding and throw a new `ApiMalformedResponseException` (retryable — it's usually a
     transient captive portal) with a human message ("The server returned something that
     isn't JSON — check the server URL, or are you behind a Wi-Fi login page?"). Make the
     DTO `fromJson`s throw the same typed exception via small checked helpers
     (`readString(json, 'id')`) instead of bare `as` casts.
  2. In `SyncService._attemptUpload`, add a final `on Object catch (e)` that marks the
     record `failed(retryable: true)` so no exception can escape with the status left at
     `uploading`.
  3. Recovery on startup: the first pass after construction (and `retryNow`) resets any
     `uploading` record to `pending`; alternatively include `uploading` in
     `listPendingOrRetryable()` — pick one and document it in the `RunStore` doc comment.
- Verify: tests — (a) a fake API that throws `FormatException` leaves the record
  `failed(retryable)` and the next pass retries it; (b) a store seeded with an `uploading`
  record is uploaded on the first pass; (c) `HttpApiClient` test with a 200 HTML body
  maps to the new exception; (d) login with an HTML 200 shows the friendly message.

### B2 — Cancelling during "Acquiring GPS" queues an empty run that the server rejects forever

The Cancel button on `LiveRunAcquiring` calls `controller.stop()`, which always writes a
`RunRecord` with `LiveMetrics.zero` and a GPX containing no track points, then fires
`runFinished()`. The server's `parse_gpx` rejects it ("no timestamped track points") with
a 400, which the phone records as `failed(retryable: false)` — a permanent "Upload
failed" line in Settings for every cancelled attempt. The same happens for a run stopped
before the first accepted fix.

- Where: `lib/features/live_run/live_run_controller.dart` (`stop`),
  `lib/core/files/run_gpx_log.dart`.
- Do: expose a `pointCount` on `RunGpxLog` (or track it in the controller); in `stop()`,
  if no point was logged, finalise, delete the GPX file, skip the sidecar and the
  `runFinished()` trigger, and return to `LiveRunIdle` instead of `LiveRunFinished`
  (there's nothing to summarise). Consider the same treatment for runs under a minimum
  (e.g. < 10 s or < 10 m) with a small "Discard run?" confirm — optional.
- Verify: controller test (after Q1's refactor) that stop-with-no-points leaves no file
  and no record; manual: Start → Cancel on the phone leaves the sync queue untouched.

### B3 — Server URL is not validated or normalised

`AuthService.setServerUrl` stores whatever was typed. `HttpApiClient._uri` concatenates
`'$baseUrl$path'`, so a trailing slash (`https://host/`) produces `https://host//api/v1/…`,
which nginx forwards unchanged and FastAPI 404s — the user sees a confusing "Upload
failed" rather than a URL hint. A missing scheme, spaces, or a `path` component behave
equally badly.

- Where: `lib/core/auth/auth_service.dart`, `lib/core/api/http_api_client.dart`,
  `lib/features/settings/settings_screen.dart`.
- Do: a pure `normalizeServerUrl(String) -> String` in `core/auth` (or `core/api`) that
  trims, requires `http`/`https` + host via `Uri.tryParse`, strips trailing slashes, and
  throws an `ArgumentError` with a clear message otherwise; call it in `setServerUrl` and
  show the error inline in the form. `_uri` builds with `Uri.parse(baseUrl).replace(path:
  …)` (or `resolve`) so a base path (`https://host/tracker`) also works.
- Verify: unit tests for the normaliser (trailing slash, no scheme, whitespace, base
  path, IPv6 literal); an `HttpApiClient` test that the request URL has a single slash.

### B4 — One 30-second timeout covers a whole multipart upload

`_requestTimeout` (30 s) wraps the entire `send()` for uploads. A long run's GPX (a few
MB) on a weak mobile link exceeds it, fails as `ApiTimeoutException`, retries with
backoff, and fails the same way every time — the record never lands.

- Where: `lib/core/api/http_api_client.dart`.
- Do: keep 30 s for JSON calls; for `uploadRun` use a much longer overall cap (e.g. 5 min)
  or, better, an idle timeout (no bytes progressed for 30 s) implemented over the
  streamed request; set `HttpClient.connectionTimeout` (e.g. 15 s) so "connect" failures
  are still quick.
- Verify: `HttpApiClient` test with a `MockClient` that delays > 30 s on upload succeeds;
  manual: a 5+ MB GPX uploads over mobile data.

### B5 (P1) — `_lastCertRejection` is shared across concurrent requests

`HttpApiClient` keeps one `_lastCertRejection` field, but two `_send` calls can overlap
(a sync pass uploading while the user signs in from Settings). A rejection from one
handshake can be attributed to the other call, or cleared before it's read.

- Do: run each `_send` in a `Zone` carrying its own rejection slot, or create the
  `HttpClient` per request (cheap enough at this call volume) and hold the rejection in a
  per-request closure. Also close the `HttpClient` when the provider is disposed
  (`ref.onDispose`) — it is never closed today.
- Verify: unit test that two concurrent `_send`s with one failing handshake report the
  exception on the right call (drive via `decideCertificateTrust` and a fake transport).

---

## 3. Workstream S — Security & privacy (P1)

### S1 — Cleartext HTTP allowed app-wide

`android:usesCleartextTraffic="true"` and iOS `NSAllowsLocalNetworking` exist for the
plain-http LAN case (WEB-PLAN §6.3), and the Settings screen warns. For internal testing
this stays. Record the decision and the exit criteria:

- Do now: move the Android setting into a `res/xml/network_security_config.xml`
  (`cleartextTrafficPermitted="true"` at base level, with a comment) so the future change
  is a one-line flip; keep the in-app warning. Add a `README`/CLAUDE.md note: before any
  external release, set it to `false`, keep `NSAllowsLocalNetworking` only if LAN use is
  still supported, and rely on TOFU pinning for self-signed servers.
- Verify: `flutter build apk --debug` still builds; http:// server still works on the S10.

### S2 — Make the trust-on-first-use dialog more informative and reversible

`badCertificateCallback` fires for every platform rejection, not just "unknown CA": an
expired or hostname-mismatched certificate from a *real* CA also lands in the dialog, and
the message doesn't say which. The pin is keyed by host only (not host:port). There is an
`untrust()` method but no UI to forget a pinned certificate.

- Do: include `cert.subject`, `cert.issuer`, `cert.startValidity`/`endValidity` in
  `ApiCertificateException` and show them in the dialog; key pins by `host:port`; add a
  "Trusted servers" list with a Forget action to Settings (reads `CertTrustStore`).
- Verify: `decideCertificateTrust` tests for the port-keyed pin; a widget test for the
  Forget action (see Q6).

### S3 — Decide what gets backed up to the cloud

Android `allowBackup` is unset (defaults to true) and iOS `Documents` is iCloud-backed-up
by default, so the full GPS history under `runs/` — and on Android the secure-storage
preference file — is included in device backups. That may be fine (it's the user's own
data) but it should be a decision, not a default.

- Do: pick one and record it in CLAUDE.md: either explicit `android:allowBackup="false"`,
  or `dataExtractionRules` excluding `runs/` and the secure-storage prefs; on iOS set
  `NSURLIsExcludedFromBackupKey` on `runs/` if excluding. Also set the iOS keychain
  accessibility for the token to `first_unlock_this_device` (no iCloud Keychain sync of a
  device token) via `IOSOptions`.
- Verify: manifest/plist diff reviewed; `flutter test` unaffected.

### S4 — Runtime notification permission is never requested

`POST_NOTIFICATIONS` is declared but not requested, so on Android 13+ the foreground-
service notification (the user's only visible sign that tracking is running in the
background) is suppressed until the user grants it in system settings. Tracking itself
still works.

- Do: on first Start (Android ≥ 13), request it. geolocator doesn't expose this;
  `permission_handler` does — **ask before adding the dependency**; the alternative is a
  ~20-line platform channel in `MainActivity.kt`. Explain in a one-line rationale before
  the system prompt.
- Verify: fresh install on the S10 (Android 13+) → Start → notification prompt → tracking
  notification visible with the screen off.

### S5 — Input hygiene on the sign-in form

Device name and email are trimmed but not checked for emptiness; the server accepts an
empty device name today (server plan S2 fixes that side). Validate non-empty email/device
name client-side with inline messages, and default the device name to the device model
(`package_info_plus` has the app version; the model needs `device_info_plus` — **ask
first**, or just default to "My phone").

---

## 4. Workstream Q — Code quality & architecture (P1/P2)

### Q1 (P1) — Make `LiveRunController` testable

The controller calls `WakelockPlus`, `PackageInfo.fromPlatform`, `newRunGpxFile`
(path_provider), `RunExportService` and `Platform` directly, so the most important
state machine in the app has no tests; the double-start, cancel-with-no-points (B2) and
export-token-guard behaviours are all verified only by hand.

- Do: introduce small interfaces + Riverpod providers: `ScreenWakeLock` (enable/disable),
  `AppInfo` (version string, platform name), `RunFilePaths` (new GPX file for a start
  time), `RunExporter` (already a class — give it a provider), and a `Clock`
  (`DateTime Function()`, same pattern as `SyncService`). Default implementations wrap
  the current calls; tests override providers with fakes and a `FakeLocationService`
  (PLAN.md §3 already calls for one).
- Verify: new `live_run_controller_test.dart` covering start → fixes → pause → resume →
  stop (segments, sidecar written before `LiveRunFinished`, `runFinished` called once),
  double-start tears down the first run, cancel with no points (B2), and the stale export
  result guard (`_runToken`).

### Q2 (P1) — Errors are swallowed with no diagnostics

`catchError((_) {})` on periodic flushes, `on Object { return null; }` in export,
`on ApiException {}` in `_fetchAnalysis`, and `main()`'s init guard all discard the error.
There is no `FlutterError.onError` / `PlatformDispatcher.instance.onError` hook, so an
uncaught async error during a run is invisible on a test phone.

- Do: a tiny `core/logging/app_log.dart` over `dart:developer` `log()` (no new package)
  with `warn/error(name, error, stack)`; call it at every swallow site; install the two
  global handlers in `main()` and route them to the same logger. For internal testing,
  keep the last ~200 lines in a ring buffer and add a "Copy diagnostics" button in
  Settings (share-sheet not required — clipboard is enough).
- Verify: unit test that the ring buffer captures a logged error; `adb logcat` shows the
  entries under the app's tag on a forced failure (e.g. server URL pointing at a closed
  port).

### Q3 (P1) — `SyncService.dispose()` can race an in-flight pass

`dispose()` closes `_statusController` while `_drainQueue` may still be awaiting an
upload; the next `_setStatus` then throws `StateError: Cannot add event after closing`.
Guard with `if (!_statusController.isClosed)` and cancel/await the in-flight pass on
dispose. Also `_runPass()` called from `whenComplete` discards its future — wrap in
`unawaited(...)` for lint clarity.

- Verify: test that disposing mid-pass (fake API that never completes until told)
  doesn't throw.

### Q4 (P2) — `FileRunStore` is O(n) per operation and grows forever

Every `updateSyncStatus`/`updateAnalysisResult` calls `listAll()` (read + parse every
sidecar), and the two `StreamProvider`s re-list on every status event. Nothing prunes old
runs; each run adds a GPX + sidecar in Documents indefinitely. Fine at tens of runs, not
at hundreds.

- Do now: keep the sidecar format but cache parsed records in memory keyed by
  `clientRunId` (invalidate on write; `listAll` re-reads only if the directory mtime
  changed), and have `updateSyncStatus` write the one sidecar it already knows the path
  of. Add a "Storage" line in Settings (count + MB) and a "Delete uploaded runs older than
  N days" action — the phone keeps the file until the user chooses otherwise, matching
  WEB-PLAN §6.3's device-scoped deletion.
- Later (already in WEB-PLAN §10): sqflite-backed `RunStore` when run history arrives.
- Verify: store tests for the cache invalidation; a test that deleting uploaded runs
  removes both files and leaves pending ones.

### Q5 (P2) — Stricter static analysis

`analysis_options.yaml` is the stock `flutter_lints` set. Turn on the analyzer's
`strict-casts`, `strict-inference`, `strict-raw-types`, and lints `unawaited_futures`,
`discarded_futures`, `avoid_dynamic_calls`, `prefer_final_locals`,
`always_declare_return_types`, `cancel_subscriptions`, `close_sinks`,
`use_build_context_synchronously` (already in the set — verify it fires on the
`_confirmCertificateTrust` path), `avoid_catches_without_on_clauses` (then justify the
deliberate `on Object` sites with a comment). Fix what it flags; B1's checked-parsing
helpers remove most `as` casts in DTOs.

- Verify: `flutter analyze` clean with the new rules; no `// ignore:` added without a
  reason comment.

### Q6 (P2) — Widget tests for the two screens

No widget tests exist; the sign-in-form bug found on device would have been caught by
one. Add `ProviderScope(overrides: …)`-based tests for: `LiveRunScreen` in each state
(idle with the mode toggle, acquiring with Cancel, active with tiles, finished with the
sync line), and `SettingsScreen` for a failed sign-in keeping the typed URL/email, the
certificate dialog flow, and the queue summary counts.

### Q7 (P2) — Small correctness/UX items

- Foreground-service text says "Tracking your run" in cycling mode → "Tracking your
  activity" (`geolocator_location_service.dart`).
- `stop()` reads `DateTime.now()` twice (filename in local time, `_startedAt` in UTC) —
  fine, but pass one `Clock` value through once Q1 lands.
- `_attemptUpload` emits `uploading` then `pending` on every trigger while signed out —
  check `auth` **before** writing `uploading` so the UI doesn't flicker and the sidecar
  isn't rewritten twice per app resume.
- `SyncStatusFailed.attempts` is persisted but `_bumpAttempts` restarts from 0 after a
  relaunch; either seed `_attemptCounts` from the persisted value on first pass or drop
  the field — currently it's misleading in the Settings error text.
- `pubspec.yaml`: description is still "A new Flutter project."; `cupertino_icons` is
  unused — tidy both. Keep `flutter_launcher_icons` config where it is.

### Q8 (P2) — CI builds nothing

`flutter.yml` runs analyze + test only, so a Gradle/plugin break (like the two compileSdk
patches in `android/build.gradle.kts`) is only ever caught on a workstation.

- Do: a second job `build-android` running `flutter build apk --debug` (Java 17 via
  `actions/setup-java`, Android SDK comes with the runner image), on PRs that touch
  `mobile/android/**`, `mobile/pubspec.*` or the workflow, plus weekly on `main`. Skip iOS
  in CI for now (needs a macOS runner; note it as a later addition). Add `pub` to the
  Dependabot config from the server plan (D5).
- Verify: the job passes on `main`; a PR bumping `flutter_secure_storage` exercises it.

### Q9 (P2) — Dependency risk log

- `media_store_plus` 0.1.3 (unmaintained ~2 years, needs the compileSdk patch and prints
  the KGP deprecation): plan its replacement with a ~50-line MediaStore platform channel
  in `MainActivity.kt` (no dependency) — do it when the next Flutter upgrade breaks it, or
  earlier if Q8's build job starts failing on it.
- `flutter_secure_storage` 11 compileSdk pin: re-check on every upgrade; remove the
  `pinCompileSdkToApp()` call for it once upstream resolves against a real SDK level.
- Everything else is at latest; keep `flutter pub outdated` in the upgrade routine.

---

## 5. Suggested delivery order

1. B1 (with the `HttpApiClient` mapping) → B3 → B2 (B2 is easier after Q1, so either do
   Q1 first or fix B2 in the controller and add its test when Q1 lands).
2. Q1, then Q2 (logging), Q3.
3. B4, B5, S2, S5.
4. S1, S3, S4 (each needs a manifest/plist decision — one PR, ask on the backup choice
   and the permission dependency).
5. Q5 (lints) — one PR that only fixes lint findings.
6. Q4, Q6, Q7, Q8, Q9 in any order.

Each PR: `flutter analyze && flutter test` from `mobile/`, a device check for anything
touching GPS/upload/manifest, Snyk code scan on changed files, CLAUDE.md status updated,
then **propose the commit and wait**.

---

## 6. Deferred until a store release is actually planned (do not do now)

- Release signing config and `applicationId` review (`android/app/build.gradle.kts`
  TODOs); `flutter build --release --obfuscate --split-debug-info`; Play App Signing.
- Remove cleartext (S1 exit criteria) and `NSAllowsLocalNetworking`.
- iOS `PrivacyInfo.xcprivacy` privacy manifest; App Store location-usage review; a
  physical-iPhone background test (still outstanding per CLAUDE.md).
- Crash reporting SDK (Sentry/Crashlytics) in place of Q2's ring buffer; analytics
  decision (default: none).
- Store listing assets, versioning/changelog policy, and a beta channel (Play internal
  testing / TestFlight) — the current `docs/deploy-guide.md` sideload flow stays the
  internal-testing path until then.
