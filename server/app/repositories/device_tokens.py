from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.device_token import DeviceToken


class DeviceTokenRepository(Protocol):
    def get_by_hash(self, token_hash: str) -> DeviceToken | None: ...
    def add(self, token: DeviceToken) -> None: ...
    def list_for_user(self, user_id: str) -> list[DeviceToken]: ...
    def get_for_user(self, user_id: str, token_id: str) -> DeviceToken | None: ...
    def revoke_all_for_user(self, user_id: str, *, except_id: str | None = None) -> None: ...
    def delete_all_for_user(self, user_id: str) -> None: ...


class SqlAlchemyDeviceTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_hash(self, token_hash: str) -> DeviceToken | None:
        stmt = select(DeviceToken).where(DeviceToken.token_hash == token_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, token: DeviceToken) -> None:
        self._session.add(token)

    def list_for_user(self, user_id: str) -> list[DeviceToken]:
        stmt = (
            select(DeviceToken)
            .where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
            .order_by(DeviceToken.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars())

    def get_for_user(self, user_id: str, token_id: str) -> DeviceToken | None:
        stmt = select(DeviceToken).where(DeviceToken.id == token_id, DeviceToken.user_id == user_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def revoke_all_for_user(self, user_id: str, *, except_id: str | None = None) -> None:
        stmt = (
            update(DeviceToken)
            .where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        if except_id is not None:
            stmt = stmt.where(DeviceToken.id != except_id)
        self._session.execute(stmt)

    def delete_all_for_user(self, user_id: str) -> None:
        """Hard delete, unlike revoke_all_for_user — used when the user
        itself is about to be deleted, so no revoked row is left behind."""
        self._session.execute(delete(DeviceToken).where(DeviceToken.user_id == user_id))
