from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db import get_session_factory


def db_session() -> Generator[Session, None, None]:
    """FastAPI dependency: one Session per request, committed on success,
    rolled back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
