"""Builds and reads the zip archive format used by activity export/import
(see docs/SERVER-PRODUCTION-PLAN.md issue #29): a manifest.json describing
each activity's metadata plus one .gpx file per activity, named by
client_activity_id so the archive is human-inspectable and the GPX content
stays byte-identical to what was originally uploaded.

The selection and import loops below are shared by app/api/v1/activities.py
and app/web/activities.py so the two entry points can't silently diverge —
see docs/SERVER-PRODUCTION-PLAN.md issue #29's review, which caught the API
and web routes duplicating (and each getting subtly wrong) the same ~50-line
per-entry import loop."""

import json
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from sqlalchemy.orm import Session

from app.api.v1.schemas import ExportManifest, ExportManifestEntry, ImportResultItem
from app.models.activity import Activity
from app.repositories.activities import SqlAlchemyActivityRepository
from app.storage.blob_store import BlobStore
from app.validation import NOTES_MAX_LENGTH, SUMMARY_MAX_BYTES, TITLE_MAX_LENGTH


class ActivityInserter(Protocol):
    def __call__(
        self, session: Session, user_id: str, entry: ExportManifestEntry, gpx_bytes: bytes
    ) -> bool:
        """Inserts one activity from a manifest entry, returning True if a
        new row was created or False if client_activity_id already existed
        for this user (a no-op skip, not a failure)."""
        ...


MANIFEST_FILENAME = "manifest.json"


class ImportArchiveError(Exception):
    """Raised when an uploaded file isn't a well-formed export archive."""


class ActivityNotFoundError(Exception):
    """Raised by select_activities_for_export when a requested id doesn't
    belong to (or doesn't exist for) the exporting user."""

    def __init__(self, activity_id: str) -> None:
        super().__init__(f"Activity not found: {activity_id}")
        self.activity_id = activity_id


def _gpx_filename(activity: Activity) -> str:
    return f"{activity.client_activity_id}.gpx"


def _failure_reason(exc: Exception) -> str:
    """A clean human-readable message for an ImportResultItem's `reason`.
    Plain str(exc) is fine for most exceptions, but insert() can raise an
    HTTPException built by app.api.v1.errors.api_error() (e.g. invalid_gpx
    from parse_gpx) — str()'ing that renders the raw
    "400: {'error': {'code': ..., 'message': ...}}" repr instead of the
    intended message, leaking internal error-shape formatting into
    user-facing API/UI text."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        message = detail["error"].get("message")
        if isinstance(message, str):
            return message
    return str(exc)


def build_export_archive(activities: list[Activity], gpx_by_activity_id: dict[str, bytes]) -> bytes:
    manifest = ExportManifest(
        activities=[
            ExportManifestEntry(
                client_activity_id=activity.client_activity_id,
                activity_type=activity.activity_type,  # type: ignore[arg-type]
                started_at=activity.started_at,
                ended_at=activity.ended_at,
                title=activity.title,
                notes=activity.notes,
                client_summary=activity.client_summary,
                source_platform=activity.source_platform,
                source_app_version=activity.source_app_version,
                gpx_filename=_gpx_filename(activity),
            )
            for activity in activities
        ]
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_FILENAME, manifest.model_dump_json(indent=2))
        for activity in activities:
            archive.writestr(_gpx_filename(activity), gpx_by_activity_id[activity.id])
    return buffer.getvalue()


def read_import_archive(
    data: bytes, max_manifest_bytes: int
) -> tuple[ExportManifest, zipfile.ZipFile]:
    """Opens the archive and validates/parses its manifest. Returns the open
    ZipFile so the caller can stream each entry's GPX bytes out one at a time
    rather than holding every activity's GPX in memory at once.

    max_manifest_bytes guards manifest.json's own *declared* (uncompressed)
    size before it's decompressed — a highly compressible manifest.json can
    otherwise reach >1000:1 compression ratios (confirmed: a ~48KB member
    inflates to ~48MB), a zip-bomb vector the per-GPX-entry size check
    elsewhere in this module doesn't cover since it only applies to GPX
    entries, not manifest.json itself."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportArchiveError("Not a valid zip archive") from exc

    if MANIFEST_FILENAME not in archive.namelist():
        raise ImportArchiveError(f"Archive is missing {MANIFEST_FILENAME}")

    manifest_info = archive.getinfo(MANIFEST_FILENAME)
    if manifest_info.file_size > max_manifest_bytes:
        raise ImportArchiveError(f"{MANIFEST_FILENAME} exceeds the {max_manifest_bytes}-byte limit")

    try:
        manifest = ExportManifest.model_validate_json(archive.read(MANIFEST_FILENAME))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ImportArchiveError(f"Could not parse {MANIFEST_FILENAME}: {exc}") from exc

    return manifest, archive


def select_activities_for_export(
    session: Session, user_id: str, activity_ids: list[str] | None
) -> list[Activity]:
    """Loads every activity the caller owns (activity_ids=None) or just the
    given ids — raising ActivityNotFoundError for any id that doesn't belong
    to (or doesn't exist for) this user, so a caller can't be tricked into
    confirming another user's activity id exists via a 200 vs 404 response."""
    activities_repo = SqlAlchemyActivityRepository(session)
    if activity_ids is None:
        selected: list[Activity] = []
        cursor = None
        while True:
            page = activities_repo.list_for_user(user_id, limit=200, cursor=cursor)
            selected.extend(page.activities)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return selected

    selected = []
    for activity_id in activity_ids:
        activity = activities_repo.get_by_id_for_user(user_id, activity_id)
        if activity is None:
            raise ActivityNotFoundError(activity_id)
        selected.append(activity)
    return selected


def export_activities_archive(
    session: Session, blob_store: BlobStore, user_id: str, activity_ids: list[str] | None
) -> bytes:
    """Builds the export archive, silently excluding any activity whose GPX
    blob has gone missing on disk (an orphaned row — should never happen
    given how carefully app/storage/blob_store.py and the delete routes keep
    row/blob writes consistent, but a single lost file must not crash the
    export for every other activity the user is trying to back up)."""
    selected = select_activities_for_export(session, user_id, activity_ids)
    gpx_by_activity_id: dict[str, bytes] = {}
    available: list[Activity] = []
    for activity in selected:
        try:
            gpx_by_activity_id[activity.id] = blob_store.get(activity.gpx_blob_key)
        except FileNotFoundError:
            continue
        available.append(activity)
    return build_export_archive(available, gpx_by_activity_id)


@dataclass(frozen=True)
class ImportSummary:
    imported: int
    skipped: int
    failed: int
    items: list[ImportResultItem]


def run_import(
    session: Session,
    user_id: str,
    manifest: ExportManifest,
    zip_archive: zipfile.ZipFile,
    max_gpx_bytes: int,
    insert: ActivityInserter,
) -> ImportSummary:
    """Processes every manifest entry, inserting via `insert` (the race-safe
    _insert_activity_with_gpx from app.api.v1.activities). One bad entry must
    never abort the whole batch, but nor may a later failure roll back an
    earlier entry's successful insert — db_session only commits once, at the
    very end of the request, so each entry gets its own SAVEPOINT via
    begin_nested() and only that savepoint is rolled back on failure."""
    items: list[ImportResultItem] = []
    for entry in manifest.activities:
        if len(json.dumps(entry.client_summary).encode()) > SUMMARY_MAX_BYTES:
            items.append(
                ImportResultItem(
                    client_activity_id=entry.client_activity_id,
                    status="failed",
                    reason=f"client_summary exceeds the {SUMMARY_MAX_BYTES}-byte limit",
                )
            )
            continue
        if (entry.title is not None and len(entry.title) > TITLE_MAX_LENGTH) or (
            entry.notes is not None and len(entry.notes) > NOTES_MAX_LENGTH
        ):
            items.append(
                ImportResultItem(
                    client_activity_id=entry.client_activity_id,
                    status="failed",
                    reason="title or notes exceed the allowed length",
                )
            )
            continue

        try:
            info = zip_archive.getinfo(entry.gpx_filename)
        except KeyError:
            items.append(
                ImportResultItem(
                    client_activity_id=entry.client_activity_id,
                    status="failed",
                    reason=f"Archive is missing {entry.gpx_filename}",
                )
            )
            continue
        if info.file_size > max_gpx_bytes:
            items.append(
                ImportResultItem(
                    client_activity_id=entry.client_activity_id,
                    status="failed",
                    reason=f"GPX exceeds the {max_gpx_bytes}-byte limit",
                )
            )
            continue

        gpx_bytes = zip_archive.read(entry.gpx_filename)
        try:
            with session.begin_nested():
                created = insert(session, user_id, entry, gpx_bytes)
        except Exception as exc:  # one bad entry must not abort the whole import batch
            items.append(
                ImportResultItem(
                    client_activity_id=entry.client_activity_id,
                    status="failed",
                    reason=_failure_reason(exc),
                )
            )
            continue

        items.append(
            ImportResultItem(
                client_activity_id=entry.client_activity_id,
                status="imported" if created else "skipped",
                reason=None if created else "Activity already exists",
            )
        )

    return ImportSummary(
        imported=sum(1 for item in items if item.status == "imported"),
        skipped=sum(1 for item in items if item.status == "skipped"),
        failed=sum(1 for item in items if item.status == "failed"),
        items=items,
    )
