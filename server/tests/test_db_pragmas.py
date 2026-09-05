"""R2 (docs/SERVER-PRODUCTION-PLAN.md): busy_timeout must be set so two
connections racing a write wait briefly instead of failing immediately with
"database is locked"."""

import threading

from sqlalchemy import text

from app.db import create_db_engine


def test_busy_timeout_pragma_is_applied(tmp_path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'pragma_check.db'}")
    with engine.connect() as conn:
        value = conn.execute(text("PRAGMA busy_timeout")).scalar_one()
    assert value == 5000


def test_concurrent_writers_do_not_raise_database_is_locked(tmp_path) -> None:
    from sqlalchemy import Column, Integer
    from sqlalchemy.orm import declarative_base, sessionmaker

    engine = create_db_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    base = declarative_base()

    class T(base):
        __tablename__ = "t"
        id = Column(Integer, primary_key=True)

    base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    errors: list[Exception] = []

    def write(value: int) -> None:
        try:
            with session_factory() as session:
                session.add(T(id=value))
                session.commit()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(1, 11)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with session_factory() as session:
        assert session.query(T).count() == 10
