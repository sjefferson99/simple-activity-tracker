"""Terrain-model elevation correction (issue #5).

Phone GPS altitude can sit tens of metres off true height, and the offset isn't
fixed per device: replaying the dev server's recordings, the S10 read ~49 m
high (height above the WGS84 ellipsoid, not sea level) and the S23 did too
until an update on 2026-09-08, after which it reads within a few metres.
Imported barometric tracks drift by ±100 m+ with the weather. None of this can
be fixed from metadata, so the offset is measured per activity: the median of
(recorded altitude - terrain height) along the route, subtracted from every
point. Shifting every point by the same amount leaves gain/loss untouched, so
they still match the phone's live figure (app/analysis/elevation.py). A track
with no altitude at all takes the terrain height at each point instead.

Terrain heights come from the AWS open-data Terrain Tiles (Mapzen's composite
model, mostly SRTM-derived at 1 arc-second, ~30 m) in "skadi" .hgt tiles, one
per 1°x1° cell, cached on disk (still gzipped) by TileCache. SRTM is a surface model (it sees
tree tops and roofs), which is why it's used for the level here and not for
gain/loss.

The correction lands in result["elevation"]["terrain"] — see
TerrainCorrection — and is reused on re-analysis, so a stored activity keeps
its correction even if the tile cache is lost or the setting turned off.
"""

import gzip
import logging
import math
import statistics
import struct
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, TypedDict

from app.analysis.track import Point, Segment, Track

log = logging.getLogger(__name__)

TERRAIN_DATASET = "aws-terrain-tiles"

# How many points along the route the offset is measured at. The median of a
# few hundred is as stable as the median of every point, at a fraction of the
# lookups on a 13,000-fix walk.
_OFFSET_SAMPLE_POINTS = 500
# Below this many points with both a recorded altitude and terrain data (a
# route over the sea, past SRTM's 60°N/56°S coverage), there's no trustworthy
# offset.
_MIN_OFFSET_SAMPLES = 10

_VOID = -32768  # SRTM's "no data" value
# After a failed download, don't retry the same tile for this long: a startup
# reanalyze with no network would otherwise sit through a timeout for every
# activity in that area instead of one.
_RETRY_AFTER_FAILURE_S = 600.0
# Unpacked tiles kept in memory (~25 MB each): two covers a route crossing a
# tile edge without unpacking on every point.
_TILES_IN_MEMORY = 2
_MAX_TILE_DOWNLOAD_BYTES = 40 * 1024 * 1024
# 1 and 3 arc-second tiles; the size of the decompressed file says which.
_TILE_SIDES = {3601 * 3601 * 2: 3601, 1201 * 1201 * 2: 1201}


class TerrainUnavailableError(Exception):
    """A tile is needed but couldn't be fetched (network, or the source)."""


class TerrainCorrection(TypedDict, total=False):
    """result["elevation"]["terrain"]. status:
    - applied: corrected; method "offset" (offset_m subtracted from every
      recorded altitude) or "profile" (no recorded altitude, terrain used).
    - pending: correction is on but a tile couldn't be fetched; retried on
      the next startup.
    - no_data: the terrain dataset doesn't cover this route.
    - disabled: correction is off (SR_TERRAIN_CORRECTION) and nothing stored.
    """

    status: Literal["applied", "pending", "no_data", "disabled"]
    method: Literal["offset", "profile"]
    offset_m: float
    dataset: str


def tile_name(lat: float, lon: float) -> str:
    """Skadi tile name of the 1°x1° cell holding (lat, lon), e.g. N50W002."""
    la, lo = math.floor(lat), math.floor(lon)
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


Fetch = Callable[[str], bytes | None]
"""Downloads a URL; None means the source has no such tile (open sea)."""


def http_fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310 -- https URL from settings
            data: bytes = response.read(_MAX_TILE_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):  # the skadi bucket answers 403 for a missing key
            return None
        raise TerrainUnavailableError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TerrainUnavailableError(f"{url}: {exc}") from exc
    if len(data) > _MAX_TILE_DOWNLOAD_BYTES:
        raise TerrainUnavailableError(f"{url}: larger than {_MAX_TILE_DOWNLOAD_BYTES} bytes")
    return data


class TileCache:
    """SRTM tiles on disk under `directory`, downloaded on first use from
    `url_template` ({lat_dir} e.g. N50, {name} e.g. N50W002) unless
    `allow_download` is False. Kept on disk as downloaded (gzipped, 1.5-6 MB)
    and decompressed into memory on use (~25 MB each); only the
    _TILES_IN_MEMORY most recently used stay unpacked. A tile the source
    doesn't have is remembered with a .none marker."""

    def __init__(
        self,
        directory: Path,
        url_template: str,
        *,
        allow_download: bool = True,
        fetch: Fetch = http_fetch,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dir = directory
        self._url_template = url_template
        self._allow_download = allow_download
        self._fetch = fetch
        self._clock = clock
        self._unpacked: OrderedDict[str, tuple[bytes, int]] = OrderedDict()
        self._failed_at: dict[str, float] = {}

    def elevation_at(self, lat: float, lon: float) -> float | None:
        """Bilinear-interpolated terrain height in metres, or None where the
        dataset has no data. Raises TerrainUnavailableError if the tile isn't
        cached and can't be downloaded."""
        tile = self._tile(tile_name(lat, lon))
        if tile is None:
            return None
        data, side = tile
        fx = (lon - math.floor(lon)) * (side - 1)
        fy = (math.floor(lat) + 1 - lat) * (side - 1)
        x0, y0 = int(fx), int(fy)
        x1, y1 = min(x0 + 1, side - 1), min(y0 + 1, side - 1)
        dx, dy = fx - x0, fy - y0
        corners: list[int] = [
            struct.unpack_from(">h", data, 2 * (y * side + x))[0]
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
        ]
        if _VOID in corners:
            return None
        a, b, c, d = corners
        return a * (1 - dx) * (1 - dy) + b * dx * (1 - dy) + c * (1 - dx) * dy + d * dx * dy

    def _tile(self, name: str) -> tuple[bytes, int] | None:
        if name in self._unpacked:
            self._unpacked.move_to_end(name)
            return self._unpacked[name]
        compressed = self._compressed(name)
        if compressed is None:
            return None
        tile = _unpack(name, compressed)
        self._unpacked[name] = tile
        while len(self._unpacked) > _TILES_IN_MEMORY:
            self._unpacked.popitem(last=False)
        return tile

    def _compressed(self, name: str) -> bytes | None:
        path = self._dir / f"{name}.hgt.gz"
        if path.exists():
            return path.read_bytes()
        if (self._dir / f"{name}.none").exists():
            return None
        if not self._allow_download:
            raise TerrainUnavailableError(f"tile {name} is not cached")
        failed_at = self._failed_at.get(name)
        if failed_at is not None and self._clock() - failed_at < _RETRY_AFTER_FAILURE_S:
            raise TerrainUnavailableError(f"tile {name} failed to download recently")
        try:
            return self._download(name, path)
        except TerrainUnavailableError:
            self._failed_at[name] = self._clock()
            raise

    def _download(self, name: str, path: Path) -> bytes | None:
        url = self._url_template.format(lat_dir=name[:3], name=name)
        log.info("Downloading terrain tile %s", url)
        compressed = self._fetch(url)
        self._dir.mkdir(parents=True, exist_ok=True)
        if compressed is None:
            (self._dir / f"{name}.none").touch()
            return None
        _unpack(name, compressed)  # never cache a tile that won't read back
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(compressed)
        tmp.replace(path)
        return compressed


def _unpack(name: str, compressed: bytes) -> tuple[bytes, int]:
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise TerrainUnavailableError(f"tile {name} is not valid gzip") from exc
    side = _TILE_SIDES.get(len(raw))
    if side is None:
        raise TerrainUnavailableError(f"tile {name} has an unexpected size")
    return raw, side


def reusable_correction(previous_result: dict[str, Any] | None) -> TerrainCorrection | None:
    """A stored offset correction from an earlier analysis, which stays valid
    for as long as the GPX doesn't change (it never does) — reused so a
    re-analysis never needs the tile again."""
    if not isinstance(previous_result, dict):
        return None
    elevation = previous_result.get("elevation")
    terrain = elevation.get("terrain") if isinstance(elevation, dict) else None
    if (
        isinstance(terrain, dict)
        and terrain.get("status") == "applied"
        and terrain.get("method") == "offset"
        and isinstance(terrain.get("offset_m"), int | float)
    ):
        return {
            "status": "applied",
            "method": "offset",
            "offset_m": float(terrain["offset_m"]),
            "dataset": str(terrain.get("dataset", TERRAIN_DATASET)),
        }
    return None


def correct_track(
    track: Track,
    tiles: TileCache | None,
    previous: TerrainCorrection | None = None,
) -> tuple[Track, TerrainCorrection]:
    """The track with altitudes corrected to the terrain model, and what was
    done. `tiles` None means correction is switched off; a stored `previous`
    offset is still applied then. Never raises: an unfetchable tile gives
    status "pending" and the track back unchanged."""
    if previous is not None and previous.get("method") == "offset":
        return _shift(track, previous["offset_m"]), previous
    if tiles is None:
        return track, {"status": "disabled"}

    points = [p for segment in track.segments for p in segment.points]
    has_ele = any(p.ele is not None for p in points)
    try:
        if has_ele:
            offset = _measure_offset(points, tiles)
            if offset is None:
                return track, {"status": "no_data"}
            return _shift(track, offset), {
                "status": "applied",
                "method": "offset",
                "offset_m": offset,
                "dataset": TERRAIN_DATASET,
            }
        profiled = _profile(track, tiles)
    except TerrainUnavailableError as exc:
        log.warning("Terrain correction pending: %s", exc)
        return track, {"status": "pending"}
    if all(p.ele is None for segment in profiled.segments for p in segment.points):
        return track, {"status": "no_data"}
    return profiled, {"status": "applied", "method": "profile", "dataset": TERRAIN_DATASET}


def _measure_offset(points: list[Point], tiles: TileCache) -> float | None:
    with_ele = [p for p in points if p.ele is not None]
    stride = max(1, len(with_ele) // _OFFSET_SAMPLE_POINTS)
    differences = []
    for p in with_ele[::stride]:
        terrain = tiles.elevation_at(p.lat, p.lon)
        if terrain is not None and p.ele is not None:
            differences.append(p.ele - terrain)
    if len(differences) < _MIN_OFFSET_SAMPLES:
        return None
    return round(statistics.median(differences), 1)


def _shift(track: Track, offset_m: float) -> Track:
    return _map_ele(track, lambda p: None if p.ele is None else p.ele - offset_m)


def _profile(track: Track, tiles: TileCache) -> Track:
    return _map_ele(track, lambda p: tiles.elevation_at(p.lat, p.lon))


def _map_ele(track: Track, ele_of: Callable[[Point], float | None]) -> Track:
    return replace(
        track,
        segments=[
            Segment(points=[replace(p, ele=ele_of(p)) for p in segment.points])
            for segment in track.segments
        ],
    )
