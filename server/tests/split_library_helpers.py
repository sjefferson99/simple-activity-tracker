"""Helpers for the split library tests (issue #143): build repo tarballs in
memory and swap in a fetcher that serves them, so no test touches the
network."""

import io
import json
import tarfile
from collections.abc import Callable

from app.config import get_settings
from app.split_library.fetch import ArchiveFetcher, FetchError, set_fetcher

DEFAULT_REPO = "https://github.com/example/split-templates"

HTMX = {"X-Requested-With": "htmx"}


def plan_time(*pairs: tuple[float, float | None]) -> dict[str, object]:
    return {
        "split_type": "time_min",
        "split_value": 1,
        "custom_splits": [list(p) for p in pairs],
        "targets_as": "pace",
    }


def config_file(name: str, uid: str | None = None, **plan_overrides: object) -> bytes:
    plan = plan_time((300, 1.667), (60, 2.222))
    plan.update(plan_overrides)
    document: dict[str, object] = {
        "format": "sat-split-config",
        "version": 1,
        "name": name,
        "plan": plan,
    }
    if uid:
        document["uid"] = uid
    return json.dumps(document).encode()


def make_tarball(
    files: dict[str, bytes],
    *,
    top: str = "example-split-templates-abc1234",
    commit: str | None = "abc1234def",
    symlinks: dict[str, str] | None = None,
) -> bytes:
    """A gzipped tarball like a git host's: every entry under one top
    directory, the commit in a pax global header (as GitHub does)."""
    buffer = io.BytesIO()
    pax = {"comment": commit} if commit else {}
    with tarfile.open(
        fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=pax
    ) as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for path, target in (symlinks or {}).items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buffer.getvalue()


class StubRepos:
    """Serves tarballs by archive URL substring; records every request."""

    def __init__(self) -> None:
        self.archives: dict[str, bytes] = {}
        self.errors: dict[str, str] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def serve(self, url_part: str, files: dict[str, bytes], **kwargs: object) -> None:
        self.archives[url_part] = make_tarball(files, **kwargs)  # type: ignore[arg-type]

    def fail(self, url_part: str, message: str) -> None:
        self.errors[url_part] = message

    def __call__(self, url: str, headers: dict[str, str], allow_private: bool) -> bytes:
        self.requests.append((url, dict(headers)))
        for part, message in self.errors.items():
            if part in url:
                raise FetchError(message)
        for part, data in self.archives.items():
            if part in url:
                return data
        raise FetchError("The repo host answered 404: check the URL")


def install_stub(monkeypatch, *, default_repo: str | None = DEFAULT_REPO) -> StubRepos:
    """Installs a stub fetcher (with no cache, so every sync refetches) and
    optionally turns on a default repo."""
    stub = StubRepos()
    fetcher = ArchiveFetcher(http_get=stub)
    fetcher.fetch = _uncached(fetcher)  # type: ignore[method-assign]
    set_fetcher(fetcher)
    if default_repo is not None:
        monkeypatch.setenv("SR_SPLIT_LIBRARY_DEFAULT_REPO", default_repo)
        get_settings.cache_clear()
    return stub


def _uncached(fetcher: ArchiveFetcher) -> Callable[..., bytes]:
    original = fetcher.fetch

    def fetch(*args: object, **kwargs: object) -> bytes:
        fetcher.clear()
        return original(*args, **kwargs)  # type: ignore[arg-type]

    return fetch


C25K_W1 = "11111111-0000-4000-8000-000000000001"
C25K_W2 = "11111111-0000-4000-8000-000000000002"
INTERVAL = "22222222-0000-4000-8000-000000000001"


def default_repo_files() -> dict[str, bytes]:
    return {
        "splits/couch-to-5k/_folder.json": json.dumps(
            {"name": "Couch to 5K", "description": "Nine weeks to 5K"}
        ).encode(),
        "splits/couch-to-5k/week-1-run-1.json": config_file("C25K week 1 run 1", C25K_W1),
        "splits/couch-to-5k/week-2-run-1.json": config_file("C25K week 2 run 1", C25K_W2),
        "splits/intervals/fartlek.json": config_file("Fartlek", INTERVAL),
        "README.md": b"not a split",
    }
