"""Wires app/analysis/terrain.py to the deployment's settings: one tile cache
per process, under <data_dir>/terrain."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.analysis.terrain import (
    TerrainCorrection,
    TileCache,
    correct_track,
    reusable_correction,
)
from app.analysis.track import Track
from app.config import get_settings


@lru_cache
def get_tile_cache() -> TileCache | None:
    """None when SR_TERRAIN_CORRECTION is off. Process-wide (it keeps tiles
    memory-mapped and remembers failed downloads); tests reset it in
    conftest.py alongside get_settings()."""
    settings = get_settings()
    if not settings.terrain_correction:
        return None
    return TileCache(Path(settings.data_dir) / "terrain", settings.terrain_tile_url)


def terrain_correct(
    track: Track, previous_result: dict[str, Any] | None = None
) -> tuple[Track, TerrainCorrection]:
    """Corrects `track` per the deployment's setting, reusing the offset
    stored in `previous_result` (the activity's earlier analysis) if any."""
    return correct_track(track, get_tile_cache(), reusable_correction(previous_result))
