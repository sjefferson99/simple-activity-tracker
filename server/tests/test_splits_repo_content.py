"""The repo's own splits/ folder is every user's default template library
(issue #143). Every file in it must sync cleanly: a broken one would be
skipped with a warning on every server."""

import json
from pathlib import Path

import pytest

from app.split_library import files
from app.split_library.fetch import read_archive
from tests.split_library_helpers import make_tarball

_SPLITS = Path(__file__).parent.parent.parent / "splits"
_CONFIG_FILES = sorted(p for p in _SPLITS.rglob("*.json") if p.name != files.FOLDER_META_FILE)


def test_there_are_templates() -> None:
    assert len(_CONFIG_FILES) >= 27


@pytest.mark.parametrize("path", _CONFIG_FILES, ids=lambda p: str(p.relative_to(_SPLITS)))
def test_config_file_is_valid(path: Path) -> None:
    config = files.parse_one(path.read_bytes())
    assert config.uid, "repo templates carry a uid so a moved file keeps its identity"
    assert config.plan["custom_splits"] or config.plan["rolling_target_mps"]


def test_folder_meta_files_are_valid() -> None:
    for path in _SPLITS.rglob(files.FOLDER_META_FILE):
        name, _ = files.parse_folder_meta(path.read_bytes())
        assert name


def test_uids_and_names_are_unique() -> None:
    uids = [json.loads(p.read_bytes())["uid"] for p in _CONFIG_FILES]
    names = [json.loads(p.read_bytes())["name"] for p in _CONFIG_FILES]
    assert len(set(uids)) == len(uids)
    assert len(set(names)) == len(names)


def test_whole_folder_reads_as_an_archive() -> None:
    archive = make_tarball(
        {
            f"splits/{p.relative_to(_SPLITS).as_posix()}": p.read_bytes()
            for p in _SPLITS.rglob("*.json")
        }
    )
    repo = read_archive(archive, "splits")
    assert repo.warnings == []
    assert len([k for k in repo.files if not k.endswith(files.FOLDER_META_FILE)]) == len(
        _CONFIG_FILES
    )


def test_couch_to_5k_paces() -> None:
    """Walks at 10:00 /km, runs at 7:30 /km, 5-minute walk either end."""
    walk, run = 1000 / 600, 1000 / 450
    for path in (_SPLITS / "couch-to-5k").glob("week-*.json"):
        splits = files.parse_one(path.read_bytes()).plan["custom_splits"]
        assert splits[0] == [300.0, pytest.approx(walk)]
        assert splits[-1] == [300.0, pytest.approx(walk)]
        assert {round(t, 4) for _, t in splits} <= {round(walk, 4), round(run, 4)}
