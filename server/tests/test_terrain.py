"""Terrain-model elevation correction — issue #5."""

import gzip
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.elevation import gain_and_loss
from app.analysis.terrain import (
    TerrainUnavailableError,
    TileCache,
    correct_track,
    reusable_correction,
    tile_name,
)
from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1
from app.cli import reanalyze
from app.config import get_settings
from app.db import get_session_factory
from app.models.activity_analysis import ActivityAnalysis
from app.terrain import get_tile_cache
from tests.conftest import upload_sample_activity, web_login

_SIDE = 1201  # a 3 arc-second tile: small enough to build in a test
_START = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
_URL = "https://tiles.invalid/{lat_dir}/{name}.hgt.gz"


def _tile_bytes(height_at=lambda col, row: 100 + col // 12) -> bytes:
    """Big-endian int16 grid; by default rising 1 m per 12 columns eastwards."""
    return struct.pack(
        f">{_SIDE * _SIDE}h", *(height_at(col, row) for row in range(_SIDE) for col in range(_SIDE))
    )


_TILE = _tile_bytes()


def _cache(tmp_path: Path, fetched: list[str] | None = None, **responses) -> TileCache:
    def fetch(url: str) -> bytes | None:
        if fetched is not None:
            fetched.append(url)
        name = url.rsplit("/", 1)[1].removesuffix(".hgt.gz")
        response = responses.get(name, gzip.compress(_TILE))
        if isinstance(response, Exception):
            raise response
        return response

    return TileCache(tmp_path / "terrain", _URL, fetch=fetch)


def _track(eles: list[float | None], creator: str = "Simple Activity Tracker") -> Track:
    """1 Hz fixes walking east through N50W002 (terrain ~100-200 m)."""
    points = [
        Point(
            lat=50.5,
            lon=-1.9 + i * 0.00002,
            ele=ele,
            time=_START + timedelta(seconds=i),
            accuracy_m=4.0,
            speed_mps=1.4,
        )
        for i, ele in enumerate(eles)
    ]
    return Track(segments=[Segment(points=points)], creator=creator)


def test_tile_name() -> None:
    assert tile_name(50.9, -1.34) == "N50W002"
    assert tile_name(38.09, 12.8) == "N38E012"
    assert tile_name(-33.9, 151.2) == "S34E151"


def test_tile_lookup_interpolates_and_is_cached_on_disk(tmp_path: Path) -> None:
    fetched: list[str] = []
    cache = _cache(tmp_path, fetched)
    # Column 600 of 1200 across the cell: 100 + 600 // 12 = 150 m.
    assert cache.elevation_at(50.5, -1.5) == pytest.approx(150, abs=0.5)
    assert fetched == ["https://tiles.invalid/N50/N50W002.hgt.gz"]
    assert (tmp_path / "terrain" / "N50W002.hgt.gz").exists()

    offline = TileCache(tmp_path / "terrain", _URL, allow_download=False)
    assert offline.elevation_at(50.5, -1.5) == pytest.approx(150, abs=0.5)


def test_a_tile_evicted_from_memory_is_reread_from_disk_not_downloaded(tmp_path: Path) -> None:
    fetched: list[str] = []
    cache = _cache(tmp_path, fetched)
    for lon in (-1.5, -0.5, 0.5, -1.5):  # three tiles, then the first again
        assert cache.elevation_at(50.5, lon) == pytest.approx(150, abs=0.5)
    assert len(fetched) == 3


def test_a_tile_the_source_lacks_means_no_data_and_is_remembered(tmp_path: Path) -> None:
    fetched: list[str] = []
    cache = _cache(tmp_path, fetched, N49W007=None)
    assert cache.elevation_at(49.5, -6.5) is None
    assert (
        TileCache(tmp_path / "terrain", _URL, allow_download=False).elevation_at(49.5, -6.5) is None
    )
    assert len(fetched) == 1


def test_void_cells_are_no_data(tmp_path: Path) -> None:
    cache = _cache(tmp_path, N50W002=gzip.compress(_tile_bytes(lambda col, row: -32768)))
    assert cache.elevation_at(50.5, -1.5) is None


def test_a_failed_download_is_not_retried_straight_away(tmp_path: Path) -> None:
    fetched: list[str] = []
    now = [0.0]
    cache = TileCache(
        tmp_path / "terrain",
        _URL,
        fetch=lambda url: fetched.append(url) or (_ for _ in ()).throw(TerrainUnavailableError()),
        clock=lambda: now[0],
    )
    for _ in range(3):
        with pytest.raises(TerrainUnavailableError):
            cache.elevation_at(50.5, -1.5)
    assert len(fetched) == 1
    now[0] = 601.0
    with pytest.raises(TerrainUnavailableError):
        cache.elevation_at(50.5, -1.5)
    assert len(fetched) == 2


def test_a_corrupt_download_is_unavailable_not_cached(tmp_path: Path) -> None:
    cache = _cache(tmp_path, N50W002=b"not gzip")
    with pytest.raises(TerrainUnavailableError):
        cache.elevation_at(50.5, -1.5)
    assert not (tmp_path / "terrain" / "N50W002.hgt.gz").exists()


def test_offset_correction_shifts_heights_but_not_gain(tmp_path: Path) -> None:
    """Recorded altitude 48 m above the terrain (an ellipsoid-height phone):
    the level moves, gain/loss don't."""
    cache = _cache(tmp_path)
    eles: list[float | None] = []
    for i in range(1200):
        terrain = cache.elevation_at(50.5, -1.9 + i * 0.00002)
        assert terrain is not None
        eles.append(terrain + 48 + (2 if i % 3 else -2))
    track = _track(eles)

    corrected, terrain_info = correct_track(track, cache)

    assert terrain_info["status"] == "applied"
    assert terrain_info["method"] == "offset"
    assert terrain_info["offset_m"] == pytest.approx(48 + 2, abs=0.1)  # median of the jitter
    assert gain_and_loss([s.points for s in corrected.segments]) == pytest.approx(
        gain_and_loss([s.points for s in track.segments])
    )
    plain = AnalyzerV1().analyze(track)["elevation"]
    result = AnalyzerV1().analyze(corrected, terrain=terrain_info)["elevation"]
    assert result["max_m"] == pytest.approx(plain["max_m"] - 50, abs=0.2)
    assert result["gain_m"] == pytest.approx(plain["gain_m"])
    assert result["terrain"] == terrain_info


def test_a_track_with_no_altitude_takes_the_terrain_profile(tmp_path: Path) -> None:
    track = _track([None] * 600)
    corrected, terrain_info = correct_track(track, _cache(tmp_path))
    assert terrain_info == {
        "status": "applied",
        "method": "profile",
        "dataset": "aws-terrain-tiles",
    }
    elevation = AnalyzerV1().analyze(corrected, terrain=terrain_info)["elevation"]
    assert elevation["min_m"] == pytest.approx(100 + int(0.1 * 1200) // 12, abs=1)
    assert elevation["gain_m"] is not None


def test_an_unfetchable_tile_leaves_the_track_alone_and_is_pending(tmp_path: Path) -> None:
    track = _track([60.0] * 100)
    corrected, terrain_info = correct_track(
        track, _cache(tmp_path, N50W002=TerrainUnavailableError("offline"))
    )
    assert terrain_info == {"status": "pending"}
    assert corrected is track


def test_no_terrain_coverage_is_no_data(tmp_path: Path) -> None:
    track = _track([60.0] * 100)
    _, terrain_info = correct_track(track, _cache(tmp_path, N50W002=None))
    assert terrain_info == {"status": "no_data"}


def test_switched_off_without_a_stored_offset_is_disabled() -> None:
    track = _track([60.0] * 100)
    corrected, terrain_info = correct_track(track, None)
    assert terrain_info == {"status": "disabled"}
    assert corrected is track


def test_a_stored_offset_is_reused_without_tiles() -> None:
    previous = reusable_correction(
        {
            "elevation": {
                "terrain": {
                    "status": "applied",
                    "method": "offset",
                    "offset_m": 48.0,
                    "dataset": "aws-terrain-tiles",
                }
            }
        }
    )
    assert previous is not None
    corrected, terrain_info = correct_track(_track([60.0] * 10), None, previous)
    assert terrain_info == previous
    assert corrected.segments[0].points[0].ele == pytest.approx(12.0)


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        {"elevation": None},
        {"elevation": {"terrain": {"status": "pending"}}},
        {"elevation": {"terrain": {"status": "applied", "method": "profile"}}},
        {"elevation": {"terrain": {"status": "applied", "method": "offset", "offset_m": "x"}}},
    ],
)
def test_only_a_valid_stored_offset_is_reused(stored) -> None:
    assert reusable_correction(stored) is None


# --- deployment wiring: setting, upload, startup reanalyze, web page ---------


def _enable(monkeypatch, tile_url: str = _URL) -> None:
    monkeypatch.setenv("SR_TERRAIN_CORRECTION", "true")
    monkeypatch.setenv("SR_TERRAIN_TILE_URL", tile_url)
    get_settings.cache_clear()
    get_tile_cache.cache_clear()


def _place_sample_tile() -> None:
    """The sample fixture runs at 51.5N 0.1W, i.e. tile N51W001."""
    terrain_dir = Path(get_settings().data_dir) / "terrain"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    (terrain_dir / "N51W001.hgt.gz").write_bytes(gzip.compress(_TILE))


def _terrain_of(activity_id: str) -> dict:
    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.result is not None
        return analysis.result["elevation"]["terrain"]


def test_upload_is_uncorrected_while_the_setting_is_off(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    activity_id = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()["id"]
    assert _terrain_of(activity_id) == {"status": "disabled"}


def test_turning_it_on_corrects_existing_activities_and_turning_it_off_keeps_them(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    activity_id = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()["id"]

    _enable(monkeypatch)
    _place_sample_tile()
    reanalyze(activity_id=None, all_activities=True)
    corrected = _terrain_of(activity_id)
    assert corrected["status"] == "applied"
    assert corrected["method"] == "offset"

    monkeypatch.setenv("SR_TERRAIN_CORRECTION", "false")
    get_settings.cache_clear()
    get_tile_cache.cache_clear()
    reanalyze(activity_id=activity_id, all_activities=False)
    assert _terrain_of(activity_id) == corrected


def test_a_pending_correction_is_retried_on_the_next_startup(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    # Port 9 (discard) on localhost: refused straight away, no real network.
    _enable(monkeypatch, "http://127.0.0.1:9/{lat_dir}/{name}.hgt.gz")
    activity_id = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()["id"]
    assert _terrain_of(activity_id) == {"status": "pending"}

    get_tile_cache.cache_clear()  # a restart forgets the failed download
    _place_sample_tile()
    reanalyze(activity_id=None, all_activities=True)
    assert _terrain_of(activity_id)["status"] == "applied"


def test_activity_page_says_whether_heights_were_corrected(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    activity_id = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()["id"]
    web_login(app_client, "admin@example.com", "admin-password-123")
    assert "correction is off on this server" in app_client.get(f"/activities/{activity_id}").text

    _enable(monkeypatch)
    _place_sample_tile()
    reanalyze(activity_id=activity_id, all_activities=False)
    page = app_client.get(f"/activities/{activity_id}").text
    assert "Heights corrected to terrain data" in page
    assert "m off" in page
