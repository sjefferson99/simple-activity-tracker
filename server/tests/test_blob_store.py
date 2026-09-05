import contextlib

from app.storage.blob_store import LocalFileBlobStore


def test_put_writes_no_tmp_file_leftover(tmp_path) -> None:
    store = LocalFileBlobStore(tmp_path)
    blob_key = store.put("user-1", b"hello")
    assert store.get(blob_key) == b"hello"
    leftovers = list((tmp_path / "gpx" / "user-1").glob("*.tmp"))
    assert leftovers == []


def test_put_failure_leaves_no_partial_file(tmp_path, monkeypatch) -> None:
    store = LocalFileBlobStore(tmp_path)

    real_replace = __import__("os").replace

    def failing_replace(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr("app.storage.blob_store.os.replace", failing_replace)
    try:
        with contextlib.suppress(OSError):
            store.put("user-1", b"hello")
    finally:
        monkeypatch.setattr("app.storage.blob_store.os.replace", real_replace)

    user_dir = tmp_path / "gpx" / "user-1"
    assert not user_dir.exists() or list(user_dir.iterdir()) == []
