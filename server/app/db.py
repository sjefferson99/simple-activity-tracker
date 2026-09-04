from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _enable_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    # Without this, two connections racing a write (e.g. a phone upload and a
    # browser action landing at the same moment) fail immediately with
    # "database is locked" instead of one waiting briefly for the other's
    # transaction to finish (see R2 in docs/SERVER-PRODUCTION-PLAN.md).
    cursor.execute("PRAGMA busy_timeout=5000")
    # Safe with WAL: fsyncs only at checkpoints, not every commit, trading a
    # small durability window (a handful of the most recent commits could be
    # lost in an OS crash/power loss, not an application crash) for less
    # per-write I/O — an acceptable trade for a self-hosted single-instance app.
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_db_engine(database_url: str) -> Engine:
    engine = create_engine(database_url)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_pragmas)
    return engine


@lru_cache
def get_engine() -> Engine:
    """Built lazily from get_settings() rather than at import time, so tests
    can point SR_DATABASE_URL at a tmp DB before the engine is created."""
    return create_db_engine(get_settings().database_url)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_db_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
