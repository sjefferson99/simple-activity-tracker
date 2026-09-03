import pytest

from app.analysis.v1 import ANALYSIS_VERSION
from app.cli import reanalyze
from app.db import get_session_factory
from app.models.run_analysis import AnalysisStatus, RunAnalysis
from tests.conftest import upload_sample_run


def _stale_the_analysis(run_id: str, *, version: int = 0) -> None:
    """Simulates a run analysed under an older ANALYSIS_VERSION, without
    needing a second real analyzer version to exist just for the test."""
    with get_session_factory()() as session:
        analysis = session.get(RunAnalysis, run_id)
        assert analysis is not None
        analysis.analysis_version = version
        analysis.result = {"analysis_version": version, "stale": True}
        session.commit()


def test_reanalyze_single_run_updates_it_to_the_current_version(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    upload = upload_sample_run(app_client, auth_headers, sample_gpx_bytes)
    run_id = upload.json()["id"]
    _stale_the_analysis(run_id)

    reanalyze(run_id=run_id, all_runs=False)

    with get_session_factory()() as session:
        analysis = session.get(RunAnalysis, run_id)
        assert analysis is not None
        assert analysis.analysis_version == ANALYSIS_VERSION
        assert analysis.status == AnalysisStatus.done
        assert analysis.result is not None
        assert analysis.result.get("stale") is not True


def test_reanalyze_all_only_touches_runs_older_than_current_version(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    stale_upload = upload_sample_run(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_run_id="22222222-2222-2222-2222-222222222222",
    )
    stale_id = stale_upload.json()["id"]
    _stale_the_analysis(stale_id)

    current_upload = upload_sample_run(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_run_id="33333333-3333-3333-3333-333333333333",
    )
    current_id = current_upload.json()["id"]
    with get_session_factory()() as session:
        current_before = session.get(RunAnalysis, current_id)
        assert current_before is not None
        computed_at_before = current_before.computed_at

    reanalyze(run_id=None, all_runs=True)

    with get_session_factory()() as session:
        stale_after = session.get(RunAnalysis, stale_id)
        assert stale_after is not None
        assert stale_after.analysis_version == ANALYSIS_VERSION

        # Already current — reanalyze --all should have left it untouched,
        # not recomputed and rewritten it (wasted work on a large instance).
        current_after = session.get(RunAnalysis, current_id)
        assert current_after is not None
        assert current_after.computed_at == computed_at_before


def test_reanalyze_run_id_that_does_not_exist_exits_with_an_error(app_client) -> None:
    with pytest.raises(SystemExit):
        reanalyze(run_id="00000000-0000-0000-0000-000000000000", all_runs=False)
