import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.run import Run


@dataclass(frozen=True)
class RunPage:
    runs: list[Run]
    next_cursor: str | None


def encode_cursor(started_at: datetime, run_id: str) -> str:
    raw = json.dumps([started_at.isoformat(), run_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    started_at_str, run_id = json.loads(raw)
    return datetime.fromisoformat(started_at_str), run_id


class RunRepository(Protocol):
    def get_by_id_for_user(self, user_id: str, run_id: str) -> Run | None: ...
    def get_by_client_run_id(self, user_id: str, client_run_id: str) -> Run | None: ...
    def add(self, run: Run) -> None: ...
    def list_for_user(self, user_id: str, *, limit: int, cursor: str | None) -> RunPage: ...
    def delete(self, run: Run) -> None: ...


class SqlAlchemyRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id_for_user(self, user_id: str, run_id: str) -> Run | None:
        stmt = select(Run).where(Run.id == run_id, Run.user_id == user_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_client_run_id(self, user_id: str, client_run_id: str) -> Run | None:
        stmt = select(Run).where(Run.user_id == user_id, Run.client_run_id == client_run_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, run: Run) -> None:
        self._session.add(run)

    def list_for_user(self, user_id: str, *, limit: int, cursor: str | None) -> RunPage:
        stmt = (
            select(Run)
            .where(Run.user_id == user_id)
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            started_at, run_id = decode_cursor(cursor)
            stmt = stmt.where(
                (Run.started_at < started_at) | ((Run.started_at == started_at) & (Run.id < run_id))
            )

        rows = list(self._session.execute(stmt).scalars())
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].started_at, page[-1].id) if has_more else None
        return RunPage(runs=page, next_cursor=next_cursor)

    def delete(self, run: Run) -> None:
        self._session.delete(run)
