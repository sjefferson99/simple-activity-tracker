"""R1 (docs/SERVER-PRODUCTION-PLAN.md): `simple-activity-tracker-server gc` finds (and,
with --apply, deletes) orphan GPX blobs that have no Activity row pointing
at them — leftovers from an interrupted upload/delete, or a stray *.tmp
from a crash mid atomic-write."""

from pathlib import Path

from app.cli import gc
from tests.conftest import upload_sample_activity


def test_gc_dry_run_reports_but_does_not_delete_an_orphan(
    app_client, auth_headers, sample_gpx_bytes, capsys
) -> None:
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    from app.config import get_settings

    gpx_dir = Path(get_settings().data_dir) / "gpx"
    user_dir = next(gpx_dir.iterdir())
    orphan = user_dir / "orphan.gpx"
    orphan.write_bytes(b"not a real activity's blob")

    gc(apply=False)

    captured = capsys.readouterr()
    assert str(orphan) in captured.out
    assert orphan.exists()


def test_gc_apply_deletes_the_orphan_but_not_referenced_blobs(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    from app.config import get_settings

    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, created["id"])
        assert activity is not None
        referenced_blob = Path(get_settings().data_dir) / "gpx" / activity.gpx_blob_key

    gpx_dir = Path(get_settings().data_dir) / "gpx"
    user_dir = next(gpx_dir.iterdir())
    orphan = user_dir / "orphan.gpx"
    orphan.write_bytes(b"not a real activity's blob")

    gc(apply=True)

    assert not orphan.exists()
    assert referenced_blob.exists()


def test_gc_with_no_orphans_reports_nothing_to_do(
    app_client, auth_headers, sample_gpx_bytes, capsys
) -> None:
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    gc(apply=False)

    captured = capsys.readouterr()
    assert "No orphan blobs or missing blobs found." in captured.out


def test_gc_reports_a_row_with_a_missing_blob(
    app_client, auth_headers, sample_gpx_bytes, capsys
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()

    from app.config import get_settings
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, created["id"])
        assert activity is not None
        blob_path = Path(get_settings().data_dir) / "gpx" / activity.gpx_blob_key

    blob_path.unlink()

    gc(apply=True)

    captured = capsys.readouterr()
    assert "MISSING" in captured.out
    assert str(blob_path) in captured.out
