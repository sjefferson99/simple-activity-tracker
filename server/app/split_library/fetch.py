"""Downloads a split repo as an HTTPS archive (docs/SPLIT-LIBRARY-PLAN.md §2.2):
GitHub, GitLab or Gitea/Forgejo, public or private (access token). No git
binary or clone: one tarball request, read in memory.

The URL comes from a user, so the request is guarded against server-side
request forgery: https only, and the address actually connected to (checked
after connecting, on every redirect hop, so DNS tricks can't dodge it) must be
a public one unless the admin allows private hosts. A redirect to another
host never carries the token. Download size, archive size, file count and
file size are all capped.
"""

import functools
import gzip
import hashlib
import http.client
import io
import ipaddress
import socket
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import IO, Any, Literal

HostKind = Literal["github", "gitlab", "gitea"]
HOST_KINDS: tuple[HostKind, ...] = ("github", "gitlab", "gitea")

TIMEOUT_S = 20.0
# The whole download, not just each read: a host trickling a byte every
# few seconds would otherwise hold a server thread for hours.
DOWNLOAD_DEADLINE_S = 60.0
_READ_CHUNK = 64 * 1024
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
MAX_SCANNED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000
MAX_CONFIG_FILES = 500
MAX_FILE_BYTES = 64 * 1024
# An archive fetched this recently is reused: every user is subscribed to
# the default repo, and they shouldn't each cost a download.
CACHE_SECONDS = 600.0
_CACHE_MAX_ENTRIES = 32
_USER_AGENT = "simple-activity-tracker-split-library"


class FetchError(Exception):
    """A repo couldn't be fetched or read. The message is shown to the user."""


@dataclass(frozen=True)
class RepoLocation:
    host_kind: HostKind
    host: str  # netloc, may include a port
    project: str  # "owner/repo", or "group/sub/repo" on GitLab
    web_url: str  # normalised https://host/project


def parse_repo_url(url: str, host_kind: str | None = None) -> RepoLocation:
    """Normalises a repo web URL (https://github.com/owner/repo, with or
    without .git or a trailing /tree/… part) and works out the host kind:
    given, or github.com/gitlab.com by name, else Gitea/Forgejo."""
    raw = url.strip()
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != "https":
        raise FetchError("The repo URL must start with https://")
    if not parsed.hostname or parsed.username or parsed.password:
        raise FetchError("The repo URL needs a host name and no user name or password")
    host = parsed.netloc.lower()
    segments = [s for s in parsed.path.split("/") if s]
    if host_kind not in (None, "", *HOST_KINDS):
        raise FetchError("Unknown repo host type")
    kind: HostKind
    if host_kind:
        kind = host_kind  # type: ignore[assignment]
    elif parsed.hostname == "github.com":
        kind = "github"
    elif parsed.hostname == "gitlab.com":
        kind = "gitlab"
    else:
        kind = "gitea"
    if kind == "gitlab" and "-" in segments:
        segments = segments[: segments.index("-")]
    elif kind != "gitlab":
        segments = segments[:2]
    if segments and segments[-1].endswith(".git"):
        segments[-1] = segments[-1][: -len(".git")]
    if len(segments) < 2 or any(s in (".", "..") for s in segments):
        raise FetchError("The repo URL should look like https://host/owner/repo")
    project = "/".join(segments)
    return RepoLocation(
        host_kind=kind, host=host, project=project, web_url=f"https://{host}/{project}"
    )


def archive_request(
    location: RepoLocation, ref: str, token: str | None
) -> tuple[str, dict[str, str]]:
    """The tarball URL and headers for one ref of a repo."""
    quoted_ref = urllib.parse.quote(ref, safe="")
    headers = {"User-Agent": _USER_AGENT}
    if location.host_kind == "github":
        api = (
            "https://api.github.com"
            if location.host == "github.com"
            else f"https://{location.host}/api/v3"
        )
        url = f"{api}/repos/{location.project}/tarball/{quoted_ref}"
        headers["Accept"] = "application/vnd.github+json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif location.host_kind == "gitlab":
        project = urllib.parse.quote(location.project, safe="")
        url = (
            f"https://{location.host}/api/v4/projects/{project}"
            f"/repository/archive.tar.gz?sha={quoted_ref}"
        )
        if token:
            headers["PRIVATE-TOKEN"] = token
    else:
        url = f"https://{location.host}/api/v1/repos/{location.project}/archive/{quoted_ref}.tar.gz"
        if token:
            headers["Authorization"] = f"token {token}"
    return url, headers


# --- guarded HTTP ------------------------------------------------------------


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: object, allow_private: bool = False, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        plain_connect: Callable[..., socket.socket] = socket.create_connection
        host = self.host

        def refused() -> FetchError:
            return FetchError(
                f"{host} is on a private network address; this server only fetches "
                "repos from public hosts"
            )

        # Checked twice. Before connecting, on every address the name
        # resolves to, so a private address is refused without a connection
        # attempt: otherwise "refused" vs "timed out" would let a user probe
        # which internal ports are open. Then on the connected socket (before
        # the TLS handshake), in case the name resolved differently the
        # second time (DNS rebinding).
        def guarded(*a: Any, **k: Any) -> socket.socket:
            if not allow_private:
                target_host, target_port = a[0][0], a[0][1]
                try:
                    infos = socket.getaddrinfo(target_host, target_port, type=socket.SOCK_STREAM)
                except OSError as exc:
                    raise FetchError(f"Couldn't find the repo host {host}") from exc
                if not infos or not all(is_public_address(str(i[4][0])) for i in infos):
                    raise refused()
            sock = plain_connect(*a, **k)
            if not allow_private and not is_public_address(sock.getpeername()[0]):
                sock.close()
                raise refused()
            return sock

        self._create_connection = guarded


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_private: bool) -> None:
        super().__init__()
        self._allow_private = allow_private

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        connection = functools.partial(_GuardedHTTPSConnection, allow_private=self._allow_private)
        return self.do_open(connection, req)


_AUTH_HEADERS = ("Authorization", "Private-token")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise FetchError("The repo host redirected to a non-https address")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (
            urllib.parse.urlsplit(newurl).netloc.lower()
            != urllib.parse.urlsplit(req.full_url).netloc.lower()
        ):
            for name in _AUTH_HEADERS:
                new.remove_header(name)
        return new


def _http_get(url: str, headers: dict[str, str], *, allow_private: bool) -> bytes:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _GuardedHTTPSHandler(allow_private),
        _GuardedRedirectHandler(),
    )
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https only, checked
    try:
        deadline = time.monotonic() + DOWNLOAD_DEADLINE_S
        with opener.open(request, timeout=TIMEOUT_S) as response:
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_DOWNLOAD_BYTES:
                if time.monotonic() > deadline:
                    raise FetchError("The repo host took too long to send the archive")
                chunk = response.read(min(_READ_CHUNK, MAX_DOWNLOAD_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            data = b"".join(chunks)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise FetchError(
                f"The repo host answered {exc.code}: check the URL, branch and, for a private "
                "repo, the access token"
            ) from exc
        raise FetchError(f"The repo host answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, FetchError):
            raise reason from exc
        raise FetchError(f"Couldn't reach the repo host: {reason}") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise FetchError(
            f"The repo archive is over {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB; keep split "
            "templates in a smaller repo"
        )
    return data


# --- archive reading ---------------------------------------------------------


@dataclass
class RepoFiles:
    """The .json files under the source's path, keyed by their path relative
    to it ("couch-to-5k/week-1-run-1.json")."""

    files: dict[str, bytes] = field(default_factory=dict)
    commit: str | None = None
    warnings: list[str] = field(default_factory=list)


def _clean_base(path: str) -> tuple[str, ...]:
    parts = tuple(p for p in path.strip().strip("/").split("/") if p)
    if any(p in (".", "..") for p in parts):
        raise FetchError("The folder path in the repo can't contain . or ..")
    return parts


class _LimitedReader(io.RawIOBase):
    """The decompressed archive, refusing to hand out more than `limit`
    bytes in total. tarfile reads a whole (pax) header in one call, so this
    stops a header claiming gigabytes before anything allocates it."""

    def __init__(self, inner: io.BufferedIOBase, limit: int) -> None:
        self._inner = inner
        self._left = limit

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> bytes:
        # Never ask the decompressor for more than one byte past the limit,
        # so a huge request can't allocate; fail only if that byte exists.
        want = self._left + 1 if size is None or size < 0 or size > self._left else size
        data = self._inner.read(want)
        if len(data) > self._left:
            raise FetchError("The repo archive is too large to read")
        self._left -= len(data)
        return data


def truncate_text(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def read_archive(data: bytes, path: str) -> RepoFiles:
    """Reads the .json files under `path` from a gzipped tarball whose
    entries all sit under one top-level directory (as every host's archive
    does). Nothing is written to disk."""
    base = _clean_base(path)
    result = RepoFiles()
    try:
        decompressed = gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")
        limited = _LimitedReader(decompressed, MAX_SCANNED_BYTES)
        with tarfile.open(fileobj=limited, mode="r|") as tar:
            for count, member in enumerate(tar):
                # A member's declared size is checked before tarfile skips
                # (decompresses) it, not after.
                if (
                    count >= MAX_ARCHIVE_MEMBERS
                    or tar.offset > MAX_SCANNED_BYTES
                    or member.size > MAX_SCANNED_BYTES
                ):
                    raise FetchError("The repo archive is too large to read")
                if result.commit is None:
                    comment = tar.pax_headers.get("comment")
                    if comment:
                        result.commit = comment[:100]
                if not member.isfile():
                    continue
                parts = PurePosixPath(member.name).parts[1:]  # drop the top directory
                if (
                    len(parts) <= len(base)
                    or parts[: len(base)] != base
                    or any(p in (".", "..") for p in parts)
                    or not parts[-1].lower().endswith(".json")
                ):
                    continue
                relative = "/".join(parts[len(base) :])
                if member.size > MAX_FILE_BYTES:
                    result.warnings.append(
                        truncate_text(f"{relative}: larger than {MAX_FILE_BYTES // 1024} KB")
                    )
                    continue
                if len(result.files) >= MAX_CONFIG_FILES:
                    result.warnings.append(
                        f"More than {MAX_CONFIG_FILES} files; the rest were skipped"
                    )
                    break
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                result.files[relative] = extracted.read(MAX_FILE_BYTES + 1)
    except FetchError:
        raise
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise FetchError("The repo archive couldn't be read") from exc
    return result


# --- fetcher with cache ------------------------------------------------------

Fetcher = Callable[[str, dict[str, str], bool], bytes]


class ArchiveFetcher:
    """Fetches and caches archives. Module-level singleton (get_fetcher) so
    tests can swap in a stub, reset in tests/conftest.py."""

    def __init__(self, http_get: Fetcher | None = None) -> None:
        self._http_get = http_get or (
            lambda url, headers, allow_private: _http_get(url, headers, allow_private=allow_private)
        )
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def fetch(
        self, location: RepoLocation, ref: str, token: str | None, *, allow_private: bool
    ) -> bytes:
        url, headers = archive_request(location, ref, token)
        key = hashlib.sha256(f"{url}\0{token or ''}".encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] < CACHE_SECONDS:
                return cached[1]
        data = self._http_get(url, headers, allow_private)
        with self._lock:
            self._cache[key] = (now, data)
            while len(self._cache) > _CACHE_MAX_ENTRIES:
                del self._cache[next(iter(self._cache))]
        return data

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_fetcher = ArchiveFetcher()


def get_fetcher() -> ArchiveFetcher:
    return _fetcher


def set_fetcher(fetcher: ArchiveFetcher) -> None:
    global _fetcher
    _fetcher = fetcher


def reset_fetcher() -> None:
    set_fetcher(ArchiveFetcher())
