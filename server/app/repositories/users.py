from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.user import User


class UserRepository(Protocol):
    def get_by_id(self, user_id: str) -> User | None: ...
    def get_by_email(self, email: str) -> User | None: ...
    def add(self, user: User) -> None: ...
    def list_all(self) -> list[User]: ...
    def count_admins_enabled(self) -> int: ...
    def count_runs(self, user_id: str) -> int: ...
    def last_run_at(self, user_id: str) -> datetime | None: ...
    def delete(self, user: User) -> None: ...


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, user_id: str) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, user: User) -> None:
        self._session.add(user)

    def list_all(self) -> list[User]:
        stmt = select(User).order_by(User.created_at)
        return list(self._session.execute(stmt).scalars())

    def count_admins_enabled(self) -> int:
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True), User.disabled_at.is_(None))
        )
        return self._session.execute(stmt).scalar_one()

    def count_runs(self, user_id: str) -> int:
        stmt = select(func.count()).select_from(Run).where(Run.user_id == user_id)
        return self._session.execute(stmt).scalar_one()

    def last_run_at(self, user_id: str) -> datetime | None:
        stmt = select(func.max(Run.started_at)).where(Run.user_id == user_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def delete(self, user: User) -> None:
        self._session.delete(user)
