import uuid
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    """Stores GPX file bytes, addressed by a server-generated key — never by
    the uploaded filename, so a hostile filename can't influence storage
    paths (see docs/WEB-PLAN.md §5.6)."""

    def put(self, user_id: str, data: bytes) -> str:
        """Stores data, returns the blob key to persist on the Activity row."""
        ...

    def get(self, blob_key: str) -> bytes: ...
    def delete(self, blob_key: str) -> None: ...


class LocalFileBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, user_id: str, data: bytes) -> str:
        blob_key = f"{user_id}/{uuid.uuid4()}.gpx"
        path = self._path_for(blob_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return blob_key

    def get(self, blob_key: str) -> bytes:
        return self._path_for(blob_key).read_bytes()

    def delete(self, blob_key: str) -> None:
        self._path_for(blob_key).unlink(missing_ok=True)

    def _path_for(self, blob_key: str) -> Path:
        # blob_key is always server-generated (see put()) — never derived
        # from user input — so this can't be used for path traversal.
        return self._root / "gpx" / blob_key
