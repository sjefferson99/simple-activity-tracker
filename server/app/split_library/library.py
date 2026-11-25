"""Sources, folders and sync for the split library (docs/SPLIT-LIBRARY-PLAN.md
§2). Used by both the JSON API and the web pages, which talk to this module
rather than to each other."""

import logging
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session_factory
from app.models.split_config import SplitConfig
from app.models.split_source import SplitSource, SplitSourceFolder
from app.split_library import files
from app.split_library.fetch import (
    FetchError,
    get_fetcher,
    parse_repo_url,
    read_archive,
    truncate_text,
)
from app.validation import SPLIT_CONFIG_NAME_MAX_LENGTH

log = logging.getLogger(__name__)

DEFAULT_SOURCE_NAME = "Simple Activity Tracker templates"
MAX_SOURCES_PER_USER = 20
_MAX_WARNINGS = 50


# --- sources -------------------------------------------------------------------


def default_repo_configured() -> bool:
    return bool(get_settings().split_library_default_repo.strip())


def _visible_source_condition() -> ColumnElement[bool]:
    """Enabled sources, leaving out default ones while the admin has turned
    the default repo off."""
    condition: ColumnElement[bool] = SplitSource.enabled.is_(True)
    if not default_repo_configured():
        condition = and_(condition, SplitSource.is_default.is_(False))
    return condition


def list_sources(session: Session, user_id: str) -> list[SplitSource]:
    stmt = (
        select(SplitSource)
        .where(SplitSource.user_id == user_id)
        .order_by(SplitSource.is_default.desc(), SplitSource.name)
    )
    sources = list(session.execute(stmt).scalars())
    if not default_repo_configured():
        sources = [s for s in sources if not s.is_default]
    return sources


def get_source(session: Session, user_id: str, source_id: str) -> SplitSource | None:
    source = session.execute(
        select(SplitSource).where(SplitSource.id == source_id, SplitSource.user_id == user_id)
    ).scalar_one_or_none()
    if source is not None and source.is_default and not default_repo_configured():
        return None
    return source


def folders_for(session: Session, source_ids: Iterable[str]) -> dict[str, list[SplitSourceFolder]]:
    ids = list(source_ids)
    result: dict[str, list[SplitSourceFolder]] = {i: [] for i in ids}
    if not ids:
        return result
    stmt = (
        select(SplitSourceFolder)
        .where(SplitSourceFolder.source_id.in_(ids))
        .order_by(SplitSourceFolder.display_name)
    )
    for folder in session.execute(stmt).scalars():
        result[folder.source_id].append(folder)
    return result


def template_counts(session: Session, source_ids: Iterable[str]) -> dict[tuple[str, str], int]:
    """Templates per (source id, folder)."""
    ids = list(source_ids)
    counts: dict[tuple[str, str], int] = {}
    if not ids:
        return counts
    rows = session.execute(
        select(SplitConfig.source_id, SplitConfig.folder).where(SplitConfig.source_id.in_(ids))
    )
    for source_id, folder in rows:
        key = (str(source_id), folder or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def ensure_default_source(session: Session, user_id: str) -> SplitSource | None:
    """The user's subscription to the default repo, created on first use and
    kept pointing at whatever the admin has configured."""
    settings = get_settings()
    url = settings.split_library_default_repo.strip()
    if not url:
        return None
    try:
        location = parse_repo_url(url)
    except FetchError:
        log.warning("SR_SPLIT_LIBRARY_DEFAULT_REPO is not a usable repo URL: %s", url)
        return None
    source = session.execute(
        select(SplitSource).where(SplitSource.user_id == user_id, SplitSource.is_default.is_(True))
    ).scalar_one_or_none()
    ref = settings.split_library_default_ref.strip() or "main"
    path = settings.split_library_default_path.strip().strip("/")
    if source is None:
        source = SplitSource(
            user_id=user_id,
            name=DEFAULT_SOURCE_NAME,
            url=location.web_url,
            host_kind=location.host_kind,
            ref=ref,
            path=path,
            token=None,
            enabled=True,
            is_default=True,
            warnings=[],
            created_at=datetime.now(UTC),
        )
        session.add(source)
        session.flush()
    elif (source.url, source.host_kind, source.ref, source.path) != (
        location.web_url,
        location.host_kind,
        ref,
        path,
    ):
        source.url, source.host_kind, source.ref, source.path = (
            location.web_url,
            location.host_kind,
            ref,
            path,
        )
        source.last_synced_at = None
        source.last_attempt_at = None
    return source


class SourceInputError(ValueError):
    """A user's source settings can't be used; the message is shown to them."""


def validate_source_input(
    *, url: str, host_kind: str | None, ref: str, path: str
) -> tuple[str, str, str, str]:
    """(normalised url, host kind, ref, path) or SourceInputError."""
    try:
        location = parse_repo_url(url, host_kind or None)
    except FetchError as exc:
        raise SourceInputError(str(exc)) from exc
    clean_ref = ref.strip() or "main"
    if len(clean_ref) > 200 or any(c.isspace() for c in clean_ref) or ".." in clean_ref:
        raise SourceInputError("The branch or tag name isn't valid")
    clean_path = path.strip().strip("/")
    if len(clean_path) > 500 or any(p in (".", "..") for p in clean_path.split("/")):
        raise SourceInputError("The folder path can't contain . or ..")
    return location.web_url, location.host_kind, clean_ref, clean_path


def add_source(
    session: Session,
    user_id: str,
    *,
    url: str,
    host_kind: str | None,
    ref: str,
    path: str,
    name: str | None,
    token: str | None,
) -> SplitSource:
    if not get_settings().split_sources_allow_user_repos:
        raise SourceInputError("This server only uses its default split repo")
    web_url, kind, clean_ref, clean_path = validate_source_input(
        url=url, host_kind=host_kind, ref=ref, path=path
    )
    existing = list_sources(session, user_id)
    if len(existing) >= MAX_SOURCES_PER_USER:
        raise SourceInputError(f"You can have at most {MAX_SOURCES_PER_USER} split repos")
    if any((s.url, s.ref, s.path) == (web_url, clean_ref, clean_path) for s in existing):
        raise SourceInputError("You're already subscribed to that repo")
    clean_name = (name or "").strip() or web_url.split("/", 3)[3]
    source = SplitSource(
        user_id=user_id,
        name=clean_name[:200],
        url=web_url,
        host_kind=kind,
        ref=clean_ref,
        path=clean_path,
        token=(token or "").strip() or None,
        enabled=True,
        is_default=False,
        warnings=[],
        created_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()
    return source


def delete_source(session: Session, source: SplitSource) -> None:
    session.execute(delete(SplitConfig).where(SplitConfig.source_id == source.id))
    session.execute(delete(SplitSourceFolder).where(SplitSourceFolder.source_id == source.id))
    session.flush()
    session.delete(source)
    session.flush()


def delete_user_library(session: Session, user_id: str) -> None:
    """Everything split-related a user owns; for user deletion."""
    source_ids = select(SplitSource.id).where(SplitSource.user_id == user_id)
    session.execute(delete(SplitConfig).where(SplitConfig.user_id == user_id))
    session.execute(delete(SplitSourceFolder).where(SplitSourceFolder.source_id.in_(source_ids)))
    session.execute(delete(SplitSource).where(SplitSource.user_id == user_id))


# --- what a user sees ----------------------------------------------------------


@dataclass
class VisibleConfig:
    config: SplitConfig
    folder_name: str | None  # display name
    source: SplitSource | None


def list_visible(session: Session, user_id: str) -> list[VisibleConfig]:
    """Own configs plus templates in enabled folders of enabled sources,
    sorted by name (the order older apps show them in)."""
    own = session.execute(
        select(SplitConfig).where(SplitConfig.user_id == user_id, SplitConfig.source_id.is_(None))
    ).scalars()
    result = [VisibleConfig(config=c, folder_name=c.folder, source=None) for c in own]
    rows = session.execute(
        select(SplitConfig, SplitSource, SplitSourceFolder)
        .join(SplitSource, SplitSource.id == SplitConfig.source_id)
        .join(
            SplitSourceFolder,
            and_(
                SplitSourceFolder.source_id == SplitConfig.source_id,
                SplitSourceFolder.folder == SplitConfig.folder,
            ),
        )
        .where(
            SplitSource.user_id == user_id,
            _visible_source_condition(),
            SplitSourceFolder.enabled.is_(True),
        )
    )
    result.extend(VisibleConfig(config=c, folder_name=f.display_name, source=s) for c, s, f in rows)
    result.sort(key=lambda v: (v.config.name, v.config.id))
    return result


def visible_config(session: Session, user_id: str, config_id: str) -> VisibleConfig | None:
    """One config the user can see, own or template (any folder state)."""
    config = session.execute(
        select(SplitConfig).where(SplitConfig.id == config_id, SplitConfig.user_id == user_id)
    ).scalar_one_or_none()
    if config is None:
        return None
    if config.source_id is None:
        return VisibleConfig(config=config, folder_name=config.folder, source=None)
    source = get_source(session, user_id, config.source_id)
    if source is None:
        return None
    folder = session.execute(
        select(SplitSourceFolder).where(
            SplitSourceFolder.source_id == source.id,
            SplitSourceFolder.folder == (config.folder or ""),
        )
    ).scalar_one_or_none()
    return VisibleConfig(
        config=config,
        folder_name=folder.display_name if folder else config.folder,
        source=source,
    )


def own_folders(session: Session, user_id: str) -> list[str]:
    rows = session.execute(
        select(SplitConfig.folder)
        .where(
            SplitConfig.user_id == user_id,
            SplitConfig.source_id.is_(None),
            SplitConfig.folder.is_not(None),
        )
        .distinct()
    )
    return sorted({str(f) for (f,) in rows}, key=str.casefold)


# --- import --------------------------------------------------------------------


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    renamed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _free_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    n = 2
    while True:
        suffix = f" ({n})"
        candidate = name[: SPLIT_CONFIG_NAME_MAX_LENGTH - len(suffix)].rstrip() + suffix
        if candidate not in taken:
            return candidate
        n += 1


def import_configs(
    session: Session, user_id: str, parsed: list[files.ParsedConfig]
) -> ImportResult:
    """Adds configs to the user's own library: a uid that's already there
    replaces that config; anything else is new, renamed "Name (2)" if the
    name is taken."""
    result = ImportResult()
    own = list(
        session.execute(
            select(SplitConfig).where(
                SplitConfig.user_id == user_id, SplitConfig.source_id.is_(None)
            )
        ).scalars()
    )
    by_uid = {c.uid: c for c in own}
    taken = {c.name for c in own}
    now = datetime.now(UTC)
    for item in parsed:
        existing = by_uid.get(item.uid) if item.uid else None
        if existing is not None:
            if item.name != existing.name:
                taken.discard(existing.name)
                new_name = _free_name(item.name, taken)
                if new_name != item.name:
                    result.renamed.append(f"{item.name} → {new_name}")
                existing.name = new_name
                taken.add(new_name)
            existing.plan = item.plan
            existing.folder = item.folder
            existing.updated_at = now
            result.updated += 1
            continue
        name = _free_name(item.name, taken)
        if name != item.name:
            result.renamed.append(f"{item.name} → {name}")
        config = SplitConfig(
            user_id=user_id,
            name=name,
            plan=item.plan,
            folder=item.folder,
            uid=item.uid or str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
        session.add(config)
        taken.add(name)
        if item.uid:
            by_uid[item.uid] = config
        result.created += 1
    session.flush()
    return result


# --- sync ----------------------------------------------------------------------

_sync_locks: dict[str, threading.Lock] = {}
_sync_locks_guard = threading.Lock()


def _lock_for(source_id: str) -> threading.Lock:
    with _sync_locks_guard:
        return _sync_locks.setdefault(source_id, threading.Lock())


def reset_sync_locks() -> None:
    with _sync_locks_guard:
        _sync_locks.clear()


@dataclass
class SyncResult:
    ok: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    error: str | None = None
    busy: bool = False


def _template_uid(source: SplitSource, relative: str, uid: str | None) -> str:
    if uid:
        return uid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source.url}@{source.path}#{relative}"))


def _folder_of(relative: str) -> str:
    return relative.rsplit("/", 1)[0] if "/" in relative else ""


def _default_folder_name(folder: str) -> str:
    return folder.rsplit("/", 1)[-1] if folder else "General"


def sync_source(session: Session, source: SplitSource) -> SyncResult:
    """Fetches the source's repo and makes its templates match it. A fetch
    failure leaves the existing templates alone and records the error. Only
    one sync of a source runs at a time; a second caller gets busy=True."""
    lock = _lock_for(source.id)
    if not lock.acquire(blocking=False):
        return SyncResult(ok=False, busy=True, error="A sync of this repo is already running")
    try:
        return _sync_locked(session, source)
    finally:
        lock.release()


def _sync_locked(session: Session, source: SplitSource) -> SyncResult:
    now = datetime.now(UTC)
    source.last_attempt_at = now
    if not source.is_default and not get_settings().split_sources_allow_user_repos:
        # Turning user repos off stops fetching them, not just adding them.
        message = "This server only uses its default split repo"
        source.last_error = message
        session.flush()
        return SyncResult(ok=False, error=message)
    try:
        location = parse_repo_url(source.url, source.host_kind)
        data = get_fetcher().fetch(
            location,
            source.ref,
            source.token,
            allow_private=get_settings().split_sources_allow_private_hosts,
        )
        repo = read_archive(data, source.path)
    except FetchError as exc:
        source.last_error = str(exc)
        session.flush()
        return SyncResult(ok=False, error=str(exc))

    warnings = list(repo.warnings)
    folder_meta: dict[str, tuple[str | None, str | None]] = {}
    parsed: dict[str, tuple[str, files.ParsedConfig]] = {}  # uid -> (path, config)
    for relative in sorted(repo.files):
        raw = repo.files[relative]
        folder = _folder_of(relative)
        if len(folder) > files.FOLDER_MAX_LENGTH:
            warnings.append(f"{relative}: folder path too long")
            continue
        if relative.rsplit("/", 1)[-1] == files.FOLDER_META_FILE:
            try:
                folder_meta[folder] = files.parse_folder_meta(raw)
            except files.DocumentError as exc:
                warnings.append(f"{relative}: {exc}")
            continue
        try:
            config = files.parse_one(raw)
        except files.DocumentError as exc:
            warnings.append(f"{relative}: {exc}")
            continue
        uid = _template_uid(source, relative, config.uid)
        if uid in parsed:
            warnings.append(f"{relative}: same uid as {parsed[uid][0]}, skipped")
            continue
        parsed[uid] = (relative, config)

    existing = {
        c.uid: c
        for c in session.execute(
            select(SplitConfig).where(SplitConfig.source_id == source.id)
        ).scalars()
    }
    result = SyncResult(ok=True)
    for uid, (relative, config) in parsed.items():
        folder = _folder_of(relative)
        row = existing.pop(uid, None)
        if row is None:
            session.add(
                SplitConfig(
                    user_id=source.user_id,
                    source_id=source.id,
                    uid=uid,
                    name=config.name,
                    folder=folder,
                    source_path=relative[:500],
                    plan=config.plan,
                    created_at=now,
                    updated_at=now,
                )
            )
            result.added += 1
        elif (row.name, row.folder, row.plan, row.source_path) != (
            config.name,
            folder,
            config.plan,
            relative,
        ):
            row.name, row.folder, row.plan, row.source_path = (
                config.name,
                folder,
                config.plan,
                relative[:500],
            )
            row.updated_at = now
            result.updated += 1
    for row in existing.values():
        session.delete(row)
        result.removed += 1
    session.flush()

    used_folders = {_folder_of(relative) for relative, _ in parsed.values()}
    folder_rows = {
        f.folder: f
        for f in session.execute(
            select(SplitSourceFolder).where(SplitSourceFolder.source_id == source.id)
        ).scalars()
    }
    for folder in used_folders:
        name, description = folder_meta.get(folder, (None, None))
        display = (name or _default_folder_name(folder))[: files.FOLDER_MAX_LENGTH]
        folder_row = folder_rows.pop(folder, None)
        if folder_row is None:
            session.add(
                SplitSourceFolder(
                    source_id=source.id,
                    folder=folder,
                    display_name=display,
                    description=description,
                    enabled=True,
                )
            )
        else:
            folder_row.display_name, folder_row.description = display, description
    for stale in folder_rows.values():
        session.delete(stale)

    source.last_synced_at = now
    source.last_commit = repo.commit
    source.last_error = None
    source.warnings = [truncate_text(w) for w in warnings[:_MAX_WARNINGS]]
    session.flush()
    return result


def sync_due(source: SplitSource, now: datetime | None = None) -> bool:
    if not source.enabled:
        return False
    last = source.last_attempt_at
    if last is None:
        return True
    hours = get_settings().split_sources_sync_hours
    return (now or datetime.now(UTC)) - last >= timedelta(hours=hours)


def due_source_ids(session: Session, user_id: str) -> list[str]:
    return [s.id for s in list_sources(session, user_id) if sync_due(s)]


def sync_in_background(source_ids: list[str]) -> None:
    """For a BackgroundTask: owns its own session (the request's is closed by
    the time this runs, see app/activity_import_jobs.py)."""
    for source_id in source_ids:
        session = get_session_factory()()
        try:
            source = session.get(SplitSource, source_id)
            if source is None or not sync_due(source):
                continue
            sync_source(session, source)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("Background sync of split source %s failed", source_id)
        finally:
            session.close()
