from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.web_session import WebSession


class WebSessionRepository(Protocol):
    def get_by_id(self, session_id: str) -> WebSession | None: ...
    def add(self, session_row: WebSession) -> None: ...
    def list_active_for_user(self, user_id: str) -> list[WebSession]: ...
    def get_active_for_user(self, user_id: str, session_id: str) -> WebSession | None: ...
    def revoke(self, session_row: WebSession) -> None: ...
    def revoke_all_for_user(self, user_id: str, *, except_id: str | None = None) -> None: ...
    def delete_all_for_user(self, user_id: str) -> None: ...


class SqlAlchemyWebSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, session_id: str) -> WebSession | None:
        stmt = select(WebSession).where(WebSession.id == session_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, session_row: WebSession) -> None:
        self._session.add(session_row)

    def list_active_for_user(self, user_id: str) -> list[WebSession]:
        stmt = (
            select(WebSession)
            .where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None))
            .order_by(WebSession.last_seen_at.desc())
        )
        return list(self._session.execute(stmt).scalars())

    def get_active_for_user(self, user_id: str, session_id: str) -> WebSession | None:
        stmt = select(WebSession).where(
            WebSession.id == session_id,
            WebSession.user_id == user_id,
            WebSession.revoked_at.is_(None),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def revoke(self, session_row: WebSession) -> None:
        session_row.revoked_at = datetime.now(UTC)

    def revoke_all_for_user(self, user_id: str, *, except_id: str | None = None) -> None:
        stmt = (
            update(WebSession)
            .where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        if except_id is not None:
            stmt = stmt.where(WebSession.id != except_id)
        self._session.execute(stmt)

    def delete_all_for_user(self, user_id: str) -> None:
        """Hard delete, unlike revoke_all_for_user — used when the user
        itself is about to be deleted, so no revoked row is left behind."""
        self._session.execute(delete(WebSession).where(WebSession.user_id == user_id))
