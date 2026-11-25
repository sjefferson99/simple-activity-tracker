"""Repo URL parsing, archive requests, tarball reading and the SSRF guards of
app/split_library/fetch.py (issue #143). No network: the guarded connection
is tested against a local listening socket."""

import email.message
import io
import socket
import threading
import urllib.request

import pytest

from app.split_library import fetch
from app.split_library.fetch import (
    FetchError,
    archive_request,
    is_public_address,
    parse_repo_url,
    read_archive,
)
from tests.split_library_helpers import config_file, make_tarball


class TestParseRepoUrl:
    def test_github_url_is_normalised(self):
        location = parse_repo_url("https://github.com/Owner/Repo.git/")
        assert location.host_kind == "github"
        assert location.project == "Owner/Repo"
        assert location.web_url == "https://github.com/Owner/Repo"

    def test_github_tree_suffix_is_dropped(self):
        location = parse_repo_url("https://github.com/o/r/tree/main/splits")
        assert location.project == "o/r"

    def test_gitlab_subgroups_are_kept(self):
        location = parse_repo_url("https://gitlab.com/group/sub/repo/-/tree/main")
        assert location.host_kind == "gitlab"
        assert location.project == "group/sub/repo"

    def test_other_hosts_default_to_gitea(self):
        location = parse_repo_url("https://git.example.org:3000/me/splits")
        assert location.host_kind == "gitea"
        assert location.host == "git.example.org:3000"

    def test_explicit_kind_wins(self):
        assert parse_repo_url("https://code.example.org/a/b", "gitlab").host_kind == "gitlab"

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/o/r",
            "file:///etc/passwd",
            "https://github.com/onlyowner",
            "https://user:pw@github.com/o/r",
            "https:///o/r",
            "https://example.org/../r",
        ],
    )
    def test_rejects_unusable_urls(self, url):
        with pytest.raises(FetchError):
            parse_repo_url(url)

    def test_rejects_unknown_kind(self):
        with pytest.raises(FetchError):
            parse_repo_url("https://example.org/a/b", "svn")


class TestArchiveRequest:
    def test_github_uses_api_tarball_with_bearer(self):
        url, headers = archive_request(parse_repo_url("https://github.com/o/r"), "main", "tok")
        assert url == "https://api.github.com/repos/o/r/tarball/main"
        assert headers["Authorization"] == "Bearer tok"
        assert "User-Agent" in headers

    def test_github_without_token_sends_no_auth(self):
        _, headers = archive_request(parse_repo_url("https://github.com/o/r"), "main", None)
        assert "Authorization" not in headers

    def test_gitlab_encodes_project_and_uses_private_token(self):
        url, headers = archive_request(parse_repo_url("https://gitlab.com/g/sub/r"), "v1.0", "tok")
        assert (
            url
            == "https://gitlab.com/api/v4/projects/g%2Fsub%2Fr/repository/archive.tar.gz?sha=v1.0"
        )
        assert headers["PRIVATE-TOKEN"] == "tok"

    def test_gitea_archive(self):
        url, headers = archive_request(
            parse_repo_url("https://git.example.org/me/splits"), "feature/x", "tok"
        )
        assert url == "https://git.example.org/api/v1/repos/me/splits/archive/feature%2Fx.tar.gz"
        assert headers["Authorization"] == "token tok"


class TestReadArchive:
    def test_reads_only_json_under_path(self):
        data = make_tarball(
            {
                "splits/a/one.json": config_file("One"),
                "splits/top.json": config_file("Top"),
                "splits/a/notes.md": b"x",
                "other/three.json": config_file("Three"),
                "splitsX/four.json": config_file("Four"),
            }
        )
        repo = read_archive(data, "splits")
        assert sorted(repo.files) == ["a/one.json", "top.json"]
        assert repo.commit == "abc1234def"

    def test_empty_path_reads_whole_repo(self):
        repo = read_archive(make_tarball({"x/one.json": b"{}"}), "")
        assert list(repo.files) == ["x/one.json"]

    def test_skips_symlinks_and_oversized_files(self):
        data = make_tarball(
            {"splits/big.json": b" " * (fetch.MAX_FILE_BYTES + 1)},
            symlinks={"splits/link.json": "/etc/passwd"},
        )
        repo = read_archive(data, "splits")
        assert repo.files == {}
        assert any("big.json" in w for w in repo.warnings)

    def test_rejects_dotdot_in_path(self):
        with pytest.raises(FetchError):
            read_archive(make_tarball({}), "../etc")

    def test_garbage_is_a_fetch_error(self):
        with pytest.raises(FetchError):
            read_archive(b"not a tarball", "splits")

    def test_caps_file_count(self, monkeypatch):
        monkeypatch.setattr(fetch, "MAX_CONFIG_FILES", 2)
        data = make_tarball({f"splits/{i}.json": b"{}" for i in range(5)})
        repo = read_archive(data, "splits")
        assert len(repo.files) == 2
        assert any("skipped" in w for w in repo.warnings)

    def test_caps_scanned_size(self, monkeypatch):
        monkeypatch.setattr(fetch, "MAX_SCANNED_BYTES", 1000)
        data = make_tarball({f"pad/{i}.bin": b"x" * 2000 for i in range(3)})
        with pytest.raises(FetchError, match="too large"):
            read_archive(data, "splits")


class TestAddressGuard:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.2",
            "172.16.0.1",
            "169.254.169.254",
            "::1",
            "fd00::1",
            "::ffff:127.0.0.1",
            "0.0.0.0",  # noqa: S104 - an address under test, not a bind
            "224.0.0.1",
            "not-an-ip",
        ],
    )
    def test_private_and_special_addresses_are_not_public(self, address):
        assert not is_public_address(address)

    @pytest.mark.parametrize("address", ["140.82.112.3", "2606:4700::1111"])
    def test_public_addresses(self, address):
        assert is_public_address(address)

    def test_private_address_is_refused_without_connecting(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1)
        accepted: list[bool] = []

        def accept() -> None:
            try:
                conn, _ = listener.accept()
                accepted.append(True)
                conn.close()
            except OSError:
                accepted.append(False)

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        port = listener.getsockname()[1]
        connection = fetch._GuardedHTTPSConnection("127.0.0.1", port, timeout=2)
        with pytest.raises(FetchError, match="private network"):
            connection.connect()
        thread.join(3)
        listener.close()
        assert accepted == [False]

    def test_open_and_closed_private_ports_look_the_same(self):
        """No port-scanning oracle: a closed internal port must not answer
        "connection refused" where an open one says "private network"."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        open_port = listener.getsockname()[1]
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        closed_port = closed.getsockname()[1]
        closed.close()
        messages = []
        try:
            for port in (open_port, closed_port):
                with pytest.raises(FetchError) as excinfo:
                    fetch._http_get(f"https://127.0.0.1:{port}/x", {}, allow_private=False)
                messages.append(str(excinfo.value).replace(str(port), "PORT"))
        finally:
            listener.close()
        assert messages[0] == messages[1]
        assert "private network" in messages[0]

    def test_rebinding_is_caught_on_the_connected_socket(self, monkeypatch):
        """A name that resolves public at check time but connects somewhere
        private is still refused."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        real_getaddrinfo = socket.getaddrinfo
        calls = []

        def first_lookup_public(*a, **k):
            calls.append(a)
            if len(calls) == 1:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.3", port))]
            return real_getaddrinfo(*a, **k)

        monkeypatch.setattr(fetch.socket, "getaddrinfo", first_lookup_public)
        connection = fetch._GuardedHTTPSConnection("127.0.0.1", port, timeout=2)
        try:
            with pytest.raises(FetchError, match="private network"):
                connection.connect()
        finally:
            listener.close()

    def test_allow_private_skips_the_guard(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        connection = fetch._GuardedHTTPSConnection("127.0.0.1", port, timeout=1, allow_private=True)
        try:
            # Gets as far as the TLS handshake, which the plain socket fails.
            with pytest.raises((OSError, ConnectionError)):
                connection.connect()
        finally:
            listener.close()

    def test_unresolvable_host_is_a_fetch_error(self):
        connection = fetch._GuardedHTTPSConnection("nonexistent.invalid", 443, timeout=2)
        with pytest.raises(FetchError, match="Couldn't find"):
            connection.connect()


class TestRedirects:
    def _redirect(self, from_url: str, to_url: str) -> urllib.request.Request | None:
        handler = fetch._GuardedRedirectHandler()
        request = urllib.request.Request(  # noqa: S310 - never opened
            from_url, headers={"Authorization": "Bearer t", "PRIVATE-TOKEN": "t"}
        )
        return handler.redirect_request(
            request, io.BytesIO(), 302, "Found", email.message.Message(), to_url
        )

    def test_cross_host_redirect_drops_token(self):
        new = self._redirect(
            "https://api.github.com/repos/o/r/tarball/main",
            "https://codeload.github.com/o/r/legacy.tar.gz/main",
        )
        assert new is not None
        assert not new.has_header("Authorization")
        assert not new.has_header("Private-token")

    def test_same_host_redirect_keeps_token(self):
        new = self._redirect("https://git.example.org/a", "https://git.example.org/b")
        assert new is not None
        assert new.has_header("Authorization")

    def test_redirect_to_http_is_refused(self):
        with pytest.raises(FetchError, match="non-https"):
            self._redirect("https://github.com/a", "http://github.com/b")


class TestDenialOfServiceLimits:
    def test_slow_download_hits_the_overall_deadline(self, monkeypatch):
        class Trickle:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                return b"x"

        class Opener:
            def open(self, request, timeout):
                return Trickle()

        monkeypatch.setattr(fetch.urllib.request, "build_opener", lambda *a: Opener())
        monkeypatch.setattr(fetch, "DOWNLOAD_DEADLINE_S", -1.0)
        with pytest.raises(FetchError, match="took too long"):
            fetch._http_get("https://example.org/x", {}, allow_private=False)

    def test_download_size_cap(self, monkeypatch):
        class Flood:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                return b"x" * size

        class Opener:
            def open(self, request, timeout):
                return Flood()

        monkeypatch.setattr(fetch.urllib.request, "build_opener", lambda *a: Opener())
        monkeypatch.setattr(fetch, "MAX_DOWNLOAD_BYTES", 1000)
        with pytest.raises(FetchError, match="over"):
            fetch._http_get("https://example.org/x", {}, allow_private=False)

    def test_huge_header_is_refused_before_it_is_read(self, monkeypatch):
        """A pax header bigger than the scan limit (here a long path) is
        refused by the limited reader, not allocated."""
        monkeypatch.setattr(fetch, "MAX_SCANNED_BYTES", 4096)
        data = make_tarball({"splits/" + "a" * 20_000 + ".json": b"{}"})
        with pytest.raises(FetchError, match="too large"):
            read_archive(data, "splits")

    def test_member_declared_size_is_checked_before_skipping(self, monkeypatch):
        monkeypatch.setattr(fetch, "MAX_SCANNED_BYTES", 50_000)
        data = make_tarball({"other/big.bin": b"\0" * 60_000})
        with pytest.raises(FetchError, match="too large"):
            read_archive(data, "splits")

    def test_long_names_in_warnings_are_truncated(self):
        name = "splits/" + "b" * 1000 + ".json"
        repo = read_archive(make_tarball({name: b" " * (fetch.MAX_FILE_BYTES + 1)}), "splits")
        assert len(repo.warnings[0]) <= 300

    def test_archive_just_under_the_limit_still_reads(self, monkeypatch):
        data = make_tarball({"splits/a.json": b"{}"})
        import gzip as _gzip

        monkeypatch.setattr(fetch, "MAX_SCANNED_BYTES", len(_gzip.decompress(data)))
        assert list(read_archive(data, "splits").files) == ["a.json"]
