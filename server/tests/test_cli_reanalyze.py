import threading
import uuid

import pytest

from app.analysis.v1 import ANALYSIS_VERSION
from app.cli import reanalyze
from app.db import get_session_factory
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.reanalysis import BACKGROUND_THREAD_NAME
from tests.conftest import upload_sample_activity


def _stale_the_analysis(activity_id: str, *, version: int = 0) -> None:
    """Simulates an activity analysed under an older ANALYSIS_VERSION, without
    needing a second real analyzer version to exist just for the test."""
    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.analysis_version = version
        analysis.result = {"analysis_version": version, "stale": True}
        session.commit()


def _reanalysis_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == BACKGROUND_THREAD_NAME]


def _serve_until_reanalysis_finishes(*_args: object, **_kwargs: object) -> None:
    """Stands in for uvicorn.run(): "serves" until the background startup
    reanalysis is done, as the real server would, rather than returning
    straight away (which tells run() to stop the reanalysis)."""
    for thread in _reanalysis_threads():
        thread.join(timeout=30)
        assert not thread.is_alive()


def _upload_stale(app_client, auth_headers, gpx: bytes, count: int) -> list[str]:
    ids = []
    for index in range(count):
        upload = upload_sample_activity(
            app_client, auth_headers, gpx, client_activity_id=str(uuid.UUID(int=index + 1))
        )
        ids.append(upload.json()["id"])
        _stale_the_analysis(ids[-1])
    return sorted(ids)  # reanalyze_stale() works through them in id order


def _version_of(activity_id: str) -> int:
    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        return analysis.analysis_version


def test_reanalyze_single_activity_updates_it_to_the_current_version(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.analysis_version == ANALYSIS_VERSION
        assert analysis.status == AnalysisStatus.done
        assert analysis.result is not None
        assert analysis.result.get("stale") is not True


def test_reanalyze_all_only_touches_activities_older_than_current_version(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    stale_upload = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id="22222222-2222-2222-2222-222222222222",
    )
    stale_id = stale_upload.json()["id"]
    _stale_the_analysis(stale_id)

    current_upload = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id="33333333-3333-3333-3333-333333333333",
    )
    current_id = current_upload.json()["id"]
    with get_session_factory()() as session:
        current_before = session.get(ActivityAnalysis, current_id)
        assert current_before is not None
        computed_at_before = current_before.computed_at

    reanalyze(activity_id=None, all_activities=True)

    with get_session_factory()() as session:
        stale_after = session.get(ActivityAnalysis, stale_id)
        assert stale_after is not None
        assert stale_after.analysis_version == ANALYSIS_VERSION

        # Already current — reanalyze --all should have left it untouched,
        # not recomputed and rewritten it (wasted work on a large instance).
        current_after = session.get(ActivityAnalysis, current_id)
        assert current_after is not None
        assert current_after.computed_at == computed_at_before


def test_reanalyze_activity_id_that_does_not_exist_exits_with_an_error(app_client) -> None:
    with pytest.raises(SystemExit):
        reanalyze(activity_id="00000000-0000-0000-0000-000000000000", all_activities=False)


def test_reanalyze_picks_up_gpx_split_extension_without_touching_activity_columns(
    app_client, auth_headers
) -> None:
    """Reanalyze refreshes ActivityAnalysis.result's split_type/split_value
    from the GPX (in case the analyzer changed), but deliberately leaves
    Activity.split_type/split_value alone — those are set once at upload
    time and stay upload-time-fixed, per the project's "pre-existing
    defaults aren't backfilled" convention."""
    from app.models.activity import Activity

    ns = "https://simple-activity-tracker.local/gpx-extensions"
    gpx = (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{ns}">'
        f"<extensions><sat:split_type>time_min</sat:split_type>"
        f"<sat:split_value>5</sat:split_value></extensions>"
        '<trk><trkseg><trkpt lat="51.5" lon="-0.1"><time>2026-01-01T07:00:00Z</time></trkpt>'
        '<trkpt lat="51.51" lon="-0.1"><time>2026-01-01T07:05:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    ).encode()

    upload = upload_sample_activity(app_client, auth_headers, gpx)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)

    # Simulate an activity row set up before this GPX carried a split
    # preference (or from an older client) — reanalyze must not touch these
    # columns even though the GPX itself now has extensions.
    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.split_type = None
        activity.split_value = None
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.result is not None
        assert analysis.result["split_type"] == "time_min"
        assert analysis.result["split_value"] == 5

        activity = session.get(Activity, activity_id)
        assert activity is not None
        assert activity.split_type is None
        assert activity.split_value is None


def test_reanalyze_backfills_a_null_split_plan_from_the_gpx(app_client, auth_headers) -> None:
    """Issue #100 follow-up: an activity uploaded after the phone started
    writing split-plan extensions (#99) but before the server understood
    them (#100) has a plan-shaped GPX but a null Activity.split_plan row —
    unlike split_type/split_value (set once, never backfilled),
    split_plan must be backfilled here, or the web page's "reset to my
    uploaded plan" control and custom-plan heading/controls fix can never
    appear for such a row short of a full re-upload."""
    from app.models.activity import Activity

    ns = "https://simple-activity-tracker.local/gpx-extensions"
    gpx = (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{ns}">'
        f"<extensions><sat:split_type>distance_km</sat:split_type>"
        f"<sat:split_value>1</sat:split_value>"
        f"<sat:split_target>3.0</sat:split_target>"
        f"<sat:split_targets_as>speed</sat:split_targets_as></extensions>"
        '<trk><trkseg><trkpt lat="51.5" lon="-0.1"><time>2026-01-01T07:00:00Z</time></trkpt>'
        '<trkpt lat="51.51" lon="-0.1"><time>2026-01-01T07:05:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    ).encode()

    upload = upload_sample_activity(app_client, auth_headers, gpx)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)

    # Simulate the pre-#100 upload path: the row was inserted before the
    # server parsed these extensions at all, so split_plan is null despite
    # the GPX itself carrying a real plan.
    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.split_plan = None
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        assert activity.split_plan == {
            "rolling_target_mps": 3.0,
            "custom_splits": [],
            "targets_as": "speed",
        }


def test_reanalyze_never_overwrites_an_existing_split_plan(app_client, auth_headers) -> None:
    """A real (non-null) split_plan is the record of what the activity was
    actually uploaded with — reanalyze must leave it alone even if the GPX
    could in principle be parsed into a different-looking plan, same
    upload-time-fixed rule as split_type/split_value."""
    from app.models.activity import Activity

    ns = "https://simple-activity-tracker.local/gpx-extensions"
    gpx = (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{ns}">'
        f"<extensions><sat:split_type>distance_km</sat:split_type>"
        f"<sat:split_value>1</sat:split_value>"
        f"<sat:split_target>3.0</sat:split_target></extensions>"
        '<trk><trkseg><trkpt lat="51.5" lon="-0.1"><time>2026-01-01T07:00:00Z</time></trkpt>'
        '<trkpt lat="51.51" lon="-0.1"><time>2026-01-01T07:05:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    ).encode()

    upload = upload_sample_activity(app_client, auth_headers, gpx)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        assert activity.split_plan is not None  # sanity: the upload path set it
        sentinel = {"rolling_target_mps": 99.0, "custom_splits": [], "targets_as": "pace"}
        activity.split_plan = sentinel
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        assert activity.split_plan == sentinel


def test_reanalyze_repopulates_the_endpoint_coordinate_columns(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    """Issue #76: reanalyze is the recovery path for rows analyzed before
    start_lat/start_lon/end_lat/end_lon existed (all null) — it must fill
    them in from the refreshed result, the same way it already does for the
    R8 track cache (see test_reanalyze_repopulates_the_cached_track above)."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.start_lat = None
        analysis.start_lon = None
        analysis.end_lat = None
        analysis.end_lon = None
        analysis.analysis_version = 0
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.result is not None
        assert analysis.start_lat == analysis.result["start"]["lat"]
        assert analysis.start_lon == analysis.result["start"]["lon"]
        assert analysis.end_lat == analysis.result["end"]["lat"]
        assert analysis.end_lon == analysis.result["end"]["lon"]


def test_reanalyze_leaves_coordinates_null_for_a_failed_analysis(app_client, auth_headers) -> None:
    """A GPX that fails to analyze (parse error at reanalyze time) must not
    leave stale/wrong coordinates behind — endpoints_from_result(None)
    returns all-None, mirroring distance_and_duration_from_result's 0/0."""
    from app.models.activity import Activity

    ns = "https://simple-activity-tracker.local/gpx-extensions"
    gpx = (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{ns}">'
        '<trk><trkseg><trkpt lat="51.5" lon="-0.1"><time>2026-01-01T07:00:00Z</time></trkpt>'
        '<trkpt lat="51.51" lon="-0.1"><time>2026-01-01T07:05:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    ).encode()
    upload = upload_sample_activity(app_client, auth_headers, gpx)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.gpx_blob_key = "does-not-exist-on-disk.gpx"
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.status == AnalysisStatus.failed
        assert analysis.start_lat is None
        assert analysis.start_lon is None
        assert analysis.end_lat is None
        assert analysis.end_lon is None


def test_run_reanalyzes_stale_activities_by_default(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    """SR_AUTO_REANALYZE defaults to true: on every startup, run() must bring
    every activity analyzed under an older ANALYSIS_VERSION up to date, the
    same way `reanalyze --all` does from the CLI — this is what gets an
    analyzer bugfix (issue #83) applied to already-uploaded activities on
    upgrade, without the operator running a command by hand."""
    from app.cli import run
    from app.config import get_settings

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)
    # Pin SR_BACKUP_DIR to a writable tmp dir — run()'s default
    # SR_BACKUP_BEFORE_MIGRATE=true would otherwise try to back up to the
    # real /backups, which doesn't exist in this test environment.
    monkeypatch.setenv("SR_BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", _serve_until_reanalysis_finishes)

    try:
        run()
    finally:
        get_settings.cache_clear()

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.analysis_version == ANALYSIS_VERSION
        assert analysis.result is not None
        assert analysis.result.get("stale") is not True


def test_run_skips_reanalysis_when_auto_reanalyze_is_disabled(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    from app.cli import run
    from app.config import get_settings

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _stale_the_analysis(activity_id)
    monkeypatch.setenv("SR_AUTO_REANALYZE", "false")
    monkeypatch.setenv("SR_BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", _serve_until_reanalysis_finishes)

    try:
        run()
    finally:
        get_settings.cache_clear()

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.analysis_version == 0
        assert analysis.result is not None
        assert analysis.result.get("stale") is True


def test_reanalyze_repopulates_the_cached_track(app_client, auth_headers, sample_gpx_bytes) -> None:
    """R8 in docs/SERVER-PRODUCTION-PLAN.md: reanalyze is the recovery path
    for rows analyzed before the track cache existed (track is null) — it
    must fill it in, not just update the analysis result."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.track = None
        analysis.analysis_version = 0
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.track is not None
        assert len(analysis.track["segments"]) == 2


# --- issue #212: one transaction per activity ---------------------------------


class _Killed(BaseException):
    """Stands in for the process dying (an OOM kill, a restart) mid-run:
    a BaseException, so nothing in reanalyze_stale() swallows it."""


def test_reanalyze_all_keeps_progress_when_killed_partway(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    """Issue #212: everything used to be committed once, at the end, so an
    OOM kill partway lost all progress and the next start redid it all (and
    was killed again). Each activity now commits on its own."""
    from app.analysis.v1 import AnalyzerV1

    ids = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 3)
    real_analyze = AnalyzerV1.analyze
    calls = []

    def analyze_then_die(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise _Killed
        return real_analyze(self, *args, **kwargs)

    monkeypatch.setattr(AnalyzerV1, "analyze", analyze_then_die)
    with pytest.raises(_Killed):
        reanalyze(activity_id=None, all_activities=True)

    assert [_version_of(i) for i in ids] == [ANALYSIS_VERSION, 0, 0]
    with get_session_factory()() as session:
        first = session.get(ActivityAnalysis, ids[0])
        assert first is not None
        first_computed_at = first.computed_at

    # The "restart": only the two left behind are picked up again.
    monkeypatch.setattr(AnalyzerV1, "analyze", real_analyze)
    reanalyze(activity_id=None, all_activities=True)

    assert [_version_of(i) for i in ids] == [ANALYSIS_VERSION] * 3
    with get_session_factory()() as session:
        first = session.get(ActivityAnalysis, ids[0])
        assert first is not None
        assert first.computed_at == first_computed_at


def test_an_unexpected_error_on_one_activity_does_not_stop_the_rest(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    from app.analysis.v1 import AnalyzerV1
    from app.reanalysis import Outcome, reanalyze_stale

    ids = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 3)
    real_analyze = AnalyzerV1.analyze
    calls = []

    def analyze_with_a_bug(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TypeError("analyzer bug")
        return real_analyze(self, *args, **kwargs)

    monkeypatch.setattr(AnalyzerV1, "analyze", analyze_with_a_bug)
    counts = reanalyze_stale()

    assert counts[Outcome.error] == 1
    assert counts[Outcome.done] == 2
    # Left as it was (not stored as FAILED), so the next run retries it.
    assert [_version_of(i) for i in ids] == [0, ANALYSIS_VERSION, ANALYSIS_VERSION]


def test_reanalysis_does_not_overwrite_an_analysis_changed_meanwhile(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    """Startup reanalysis now runs while the app serves (issue #206), so a
    request can replace an activity's analysis while the background thread
    is computing a new one for it. The request's write must win."""
    from datetime import UTC, datetime

    import app.reanalysis as reanalysis
    from app.reanalysis import Outcome, reanalyze_stale

    [activity_id] = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 1)
    real_analyze = reanalysis._analyze

    def analyze_while_a_request_writes(activity, previous, blob_store):
        computed = real_analyze(activity, previous, blob_store)
        with get_session_factory()() as other:
            analysis = other.get(ActivityAnalysis, activity_id)
            assert analysis is not None
            analysis.analysis_version = ANALYSIS_VERSION
            analysis.result = {"written_by": "request"}
            analysis.computed_at = datetime.now(UTC)
            other.commit()
        return computed

    monkeypatch.setattr(reanalysis, "_analyze", analyze_while_a_request_writes)
    counts = reanalyze_stale()

    assert counts[Outcome.skipped] == 1
    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.result == {"written_by": "request"}


def test_reanalysis_skips_an_activity_deleted_meanwhile(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    import app.reanalysis as reanalysis
    from app.reanalysis import Outcome, reanalyze_stale

    [activity_id] = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 1)
    real_analyze = reanalysis._analyze

    def analyze_while_deleted(activity, previous, blob_store):
        computed = real_analyze(activity, previous, blob_store)
        response = app_client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers)
        assert response.status_code == 204
        return computed

    monkeypatch.setattr(reanalysis, "_analyze", analyze_while_deleted)
    counts = reanalyze_stale()

    assert counts[Outcome.skipped] == 1
    with get_session_factory()() as session:
        assert session.get(ActivityAnalysis, activity_id) is None


def test_reanalysis_stops_after_the_current_activity_when_asked(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    import app.reanalysis as reanalysis
    from app.reanalysis import reanalyze_stale

    ids = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 3)
    stop = threading.Event()
    real_analyze = reanalysis._analyze

    def analyze_then_shut_down(activity, previous, blob_store):
        stop.set()  # shutdown arrives while the first activity is in progress
        return real_analyze(activity, previous, blob_store)

    monkeypatch.setattr(reanalysis, "_analyze", analyze_then_shut_down)
    reanalyze_stale(stop)

    assert [_version_of(i) for i in ids] == [ANALYSIS_VERSION, 0, 0]


# --- issues #206/#213: serve first, reanalyse in the background ---------------


def test_run_serves_before_the_startup_reanalysis_finishes(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    """Issues #206/#213: a long startup reanalysis used to run before uvicorn
    started, so /healthz stayed silent until it was done and the container
    went unhealthy. run() must reach uvicorn.run() while it's still going."""
    import app.reanalysis as reanalysis
    from app.cli import run
    from app.config import get_settings

    [activity_id] = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 1)
    release = threading.Event()
    real_analyze = reanalysis._analyze

    def slow_analyze(activity, previous, blob_store):
        assert release.wait(timeout=30)
        return real_analyze(activity, previous, blob_store)

    monkeypatch.setattr(reanalysis, "_analyze", slow_analyze)
    served_while_stale = []

    def serve(*args: object, **kwargs: object) -> None:
        served_while_stale.append(_version_of(activity_id) == 0)
        assert app_client.get("/healthz").status_code == 200
        release.set()
        _serve_until_reanalysis_finishes()

    monkeypatch.setenv("SR_BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", serve)
    try:
        run()
    finally:
        release.set()
        get_settings.cache_clear()

    assert served_while_stale == [True]
    assert _version_of(activity_id) == ANALYSIS_VERSION


def test_run_stops_the_background_reanalysis_on_shutdown(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    """When uvicorn returns (SIGTERM), run() asks the reanalysis to stop after
    the activity in progress and waits for it, so that one commits and the
    rest are left for the next start."""
    import app.reanalysis as reanalysis
    from app.cli import run
    from app.config import get_settings

    ids = _upload_stale(app_client, auth_headers, sample_gpx_bytes, 3)
    started = threading.Event()
    release = threading.Event()
    real_analyze = reanalysis._analyze

    def slow_analyze(activity, previous, blob_store):
        started.set()
        assert release.wait(timeout=30)
        return real_analyze(activity, previous, blob_store)

    monkeypatch.setattr(reanalysis, "_analyze", slow_analyze)

    def serve_then_shut_down(*args: object, **kwargs: object) -> None:
        assert started.wait(timeout=30)
        # Let the in-progress activity finish only after this "server" has
        # returned, i.e. once run() has asked the thread to stop.
        threading.Timer(0.2, release.set).start()

    monkeypatch.setenv("SR_BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", serve_then_shut_down)
    try:
        run()
    finally:
        release.set()
        get_settings.cache_clear()

    assert not _reanalysis_threads()
    assert [_version_of(i) for i in ids] == [ANALYSIS_VERSION, 0, 0]
