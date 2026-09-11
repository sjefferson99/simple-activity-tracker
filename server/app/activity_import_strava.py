"""Imports activities from a Strava account export .zip (issue #61):
activities.csv at the archive root, matched via its own Filename column to
files under activities/ (each gzip-compressed GPX/TCX/FIT). Only these two
paths are ever read — a full Strava export also contains profile photos,
routes, segments, social data, etc., none of which this feature touches.

Shares the same per-entry-isolated, race-safe insert machinery as the
SAT-native import (app/activity_export.py's run_import/ActivityInserter) —
see _insert_from_strava_row in app/api/v1/activities.py, the Strava-specific
adapter around _insert_activity_with_gpx."""

import csv
import gzip
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.activity_export import ImportSummary, failure_reason
from app.analysis.fit_parser import FitNoTrackPointsError, FitParseError, parse_fit
from app.analysis.gpx_parser import GpxNoTrackPointsError, GpxParseError, parse_gpx
from app.analysis.gpx_writer import track_to_gpx_bytes
from app.analysis.tcx_parser import TcxNoTrackPointsError, TcxParseError, parse_tcx
from app.api.v1.schemas import ImportResultItem
from app.validation import NOTES_MAX_LENGTH, TITLE_MAX_LENGTH

ACTIVITIES_CSV_NAME = "activities.csv"
_GZIP_MAGIC = b"\x1f\x8b"

# Strava's CSV "Activity Type" -> SAT's activity_type column + the
# type-derived tag. Per issue #61's literal wording ("tagged as cycle or
# run where appropriate and no tag added for other activities"), only these
# two map to a type tag; everything else still gets activity_type="running"
# (the column's own existing default — every row needs *some* value since
# it's NOT NULL) but no type tag, only "Strava".
_TYPE_TO_ACTIVITY_TYPE_AND_TAG = {
    "Ride": ("cycling", "cycling"),
    "Virtual Ride": ("cycling", "cycling"),
    "Run": ("running", "running"),
}
STRAVA_TAG_NAME = "Strava"


@dataclass(frozen=True)
class StravaCsvRow:
    activity_id: str
    activity_date: datetime | None
    name: str | None
    description: str | None
    activity_type: str
    filename: str


class StravaImportError(Exception):
    """Raised when the uploaded file isn't a well-formed Strava export."""


class StravaNoTrackDataError(StravaImportError):
    """Raised for an activity file that parsed but has no usable track
    points — most commonly a genuinely GPS-less indoor/virtual activity
    (e.g. a trainer ride recorded with only power/heart-rate). Reported as
    a "skipped" row, not a "failed" one, since SAT simply has nothing to
    import for these rather than having encountered an error."""


class StravaActivityInserter(Protocol):
    def __call__(
        self,
        session: Session,
        user_id: str,
        client_activity_id: str,
        activity_type: str,
        started_at: datetime,
        ended_at: datetime,
        title: str | None,
        tags: list[str],
        gpx_bytes: bytes,
    ) -> bool: ...


def _map_activity_type(strava_type: str) -> tuple[str, str | None]:
    activity_type, tag = _TYPE_TO_ACTIVITY_TYPE_AND_TAG.get(strava_type, ("running", None))
    return activity_type, tag


def _parse_activity_date(value: str) -> datetime | None:
    # Strava's export CSV format, verified against the user's real export:
    # "Sep 9, 2026, 8:58:03 PM" — locale-formatted, no explicit timezone but
    # always UTC per Strava's own documentation.
    try:
        return datetime.strptime(value, "%b %d, %Y, %I:%M:%S %p").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_activities_csv(data: bytes) -> list[StravaCsvRow]:
    """Reads activities.csv, keeping only the columns this feature needs —
    Strava's real export has ~90 columns (heart rate, power, weather, gear,
    social fields, ...) that are discarded simply by never being read,
    rather than needing explicit filtering code."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StravaImportError(f"{ACTIVITIES_CSV_NAME} is not valid UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "Activity ID" not in reader.fieldnames:
        raise StravaImportError(f"{ACTIVITIES_CSV_NAME} is missing expected columns")

    rows: list[StravaCsvRow] = []
    for raw in reader:
        activity_id = (raw.get("Activity ID") or "").strip()
        if not activity_id:
            continue
        rows.append(
            StravaCsvRow(
                activity_id=activity_id,
                activity_date=_parse_activity_date((raw.get("Activity Date") or "").strip()),
                name=(raw.get("Activity Name") or "").strip() or None,
                description=(raw.get("Activity Description") or "").strip() or None,
                activity_type=(raw.get("Activity Type") or "").strip(),
                filename=(raw.get("Filename") or "").strip(),
            )
        )
    return rows


def read_strava_export_archive(data: bytes, max_manifest_bytes: int) -> zipfile.ZipFile:
    """Opens+validates the zip and confirms activities.csv is present. Does
    NOT eagerly read every activity file — real exports run to hundreds of
    multi-MB FIT files, so entries are streamed one at a time by
    run_strava_import instead of held in memory together.

    max_manifest_bytes guards activities.csv's own *declared* (uncompressed)
    size before it's decompressed, the same zip-bomb guard
    app/activity_export.py's read_import_archive applies to manifest.json —
    a highly compressible CSV can otherwise reach >1000:1 compression ratios
    well within the outer archive's own size limit."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise StravaImportError("Not a valid zip archive") from exc

    if ACTIVITIES_CSV_NAME not in archive.namelist():
        raise StravaImportError(f"Archive is missing {ACTIVITIES_CSV_NAME}")

    csv_info = archive.getinfo(ACTIVITIES_CSV_NAME)
    if csv_info.file_size > max_manifest_bytes:
        raise StravaImportError(
            f"{ACTIVITIES_CSV_NAME} exceeds the {max_manifest_bytes}-byte limit"
        )
    return archive


def _decompress(raw: bytes, max_bytes: int) -> bytes:
    """Strava's activity files are gzip-compressed, but detect the actual
    gzip magic number rather than trusting the .gz suffix blindly, in case
    a future/partial export ever includes an uncompressed member.

    max_bytes bounds the *decompressed* output, not just the (already
    size-checked) compressed input — gzip's compression ratio is unbounded
    (routinely >1000:1 on repetitive data), so a small, size-limit-passing
    .gz member could otherwise expand to gigabytes via a single
    gzip.decompress() call. Reads one chunk past the limit and rejects if
    that chunk is non-empty, rather than materializing an unbounded buffer
    first and checking its length after the fact."""
    if raw[:2] == _GZIP_MAGIC:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                data = gz.read(max_bytes + 1)
        except (gzip.BadGzipFile, OSError) as exc:
            raise StravaImportError(f"Corrupt gzip data: {exc}") from exc
        if len(data) > max_bytes:
            raise StravaImportError(
                f"Decompressed activity file exceeds the {max_bytes}-byte limit"
            )
        return data
    return raw


def _to_gpx_bytes(filename: str, raw: bytes, max_decompressed_bytes: int) -> bytes:
    """Decompresses one activities/ member and returns GPX bytes ready for
    _insert_activity_with_gpx. GPX-sourced files pass through decompressed
    but otherwise byte-for-byte unchanged (no lossy re-serialization); TCX
    and FIT are parsed then converted via gpx_writer.track_to_gpx_bytes so
    the blob store/AnalyzerV1/download-as-GPX pipeline needs no format
    awareness downstream of this function."""
    data = _decompress(raw, max_decompressed_bytes)
    lower = filename.lower()
    if lower.endswith(".gpx.gz") or lower.endswith(".gpx"):
        try:
            parse_gpx(data)  # validate only — pass through the original bytes
        except GpxNoTrackPointsError as exc:
            raise StravaNoTrackDataError(f"No GPS track data ({filename})") from exc
        except GpxParseError as exc:
            raise StravaImportError(f"Could not parse GPX ({filename}): {exc}") from exc
        return data
    if lower.endswith(".tcx.gz") or lower.endswith(".tcx"):
        try:
            track = parse_tcx(data)
        except TcxNoTrackPointsError as exc:
            raise StravaNoTrackDataError(f"No GPS track data ({filename})") from exc
        except TcxParseError as exc:
            raise StravaImportError(f"Could not parse TCX ({filename}): {exc}") from exc
        return track_to_gpx_bytes(track)
    if lower.endswith(".fit.gz") or lower.endswith(".fit"):
        try:
            track = parse_fit(data)
        except FitNoTrackPointsError as exc:
            raise StravaNoTrackDataError(f"No GPS track data ({filename})") from exc
        except FitParseError as exc:
            raise StravaImportError(f"Could not parse FIT ({filename}): {exc}") from exc
        return track_to_gpx_bytes(track)
    raise StravaImportError(f"Unrecognized activity file type: {filename}")


def run_strava_import(
    session: Session,
    user_id: str,
    csv_rows: list[StravaCsvRow],
    zip_archive: zipfile.ZipFile,
    max_activity_file_bytes: int,
    insert: StravaActivityInserter,
    on_progress: Callable[[int, int], None] | None = None,
) -> ImportSummary:
    """Processes every activities.csv row the same way app.activity_export's
    run_import processes manifest entries: one bad row must never abort the
    whole batch, and each row gets its own SAVEPOINT via begin_nested() so a
    later failure can't roll back an earlier row's successful insert.

    on_progress, when given, is called with (processed, total) after each
    row — the background-job wrapper in app/activity_import_jobs.py uses it
    to update the polled status endpoint. Optional so existing callers/tests
    calling run_strava_import directly are unaffected (issue #61 follow-up:
    moving the import off the request thread)."""
    total = len(csv_rows)
    items: list[ImportResultItem] = []
    for index, row in enumerate(csv_rows):
        client_activity_id = f"strava:{row.activity_id}"

        if not row.filename:
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id,
                    status="failed",
                    reason="No activity file listed for this row",
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue

        if (row.name is not None and len(row.name) > TITLE_MAX_LENGTH) or (
            row.description is not None and len(row.description) > NOTES_MAX_LENGTH
        ):
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id,
                    status="failed",
                    reason="Activity name or description exceed the allowed length",
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue

        try:
            info = zip_archive.getinfo(row.filename)
        except KeyError:
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id,
                    status="failed",
                    reason=f"Archive is missing {row.filename}",
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue
        if info.file_size > max_activity_file_bytes:
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id,
                    status="failed",
                    reason=f"{row.filename} exceeds the {max_activity_file_bytes}-byte limit",
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue

        try:
            gpx_bytes = _to_gpx_bytes(
                row.filename, zip_archive.read(row.filename), max_activity_file_bytes
            )
            track = parse_gpx(gpx_bytes)
        except StravaNoTrackDataError as exc:
            # A genuinely GPS-less activity (e.g. an indoor/virtual ride
            # recorded with only power/heart-rate) — SAT has nothing to
            # import here, but that's an expected outcome, not an error.
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id, status="skipped", reason=str(exc)
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue
        except StravaImportError as exc:
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id, status="failed", reason=str(exc)
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue

        first_segment = track.segments[0]
        last_segment = track.segments[-1]
        started_at = first_segment.points[0].time
        ended_at = last_segment.points[-1].time
        if row.activity_date is not None and started_at == ended_at:
            # A single-usable-point Track (rare, but possible) has no real
            # duration of its own — Activity Date is Strava's best-effort
            # fallback for that edge case only, not the normal source of
            # truth (the parsed track's own timestamps are authoritative).
            ended_at = row.activity_date

        activity_type, type_tag = _map_activity_type(row.activity_type)
        tags = [STRAVA_TAG_NAME] + ([type_tag] if type_tag else [])

        try:
            with session.begin_nested():
                created = insert(
                    session,
                    user_id,
                    client_activity_id,
                    activity_type,
                    started_at,
                    ended_at,
                    row.name,
                    tags,
                    gpx_bytes,
                )
        except Exception as exc:  # one bad row must not abort the whole import batch
            items.append(
                ImportResultItem(
                    client_activity_id=client_activity_id,
                    status="failed",
                    reason=failure_reason(exc),
                )
            )
            if on_progress is not None:
                on_progress(index + 1, total)
            continue

        items.append(
            ImportResultItem(
                client_activity_id=client_activity_id,
                status="imported" if created else "skipped",
                reason=None if created else "Activity already exists",
            )
        )
        if on_progress is not None:
            on_progress(index + 1, total)

    return ImportSummary(
        imported=sum(1 for item in items if item.status == "imported"),
        skipped=sum(1 for item in items if item.status == "skipped"),
        failed=sum(1 for item in items if item.status == "failed"),
        items=items,
    )
