from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.split_config import SplitConfig


class SplitConfigRepository(Protocol):
    def list_for_user(self, user_id: str) -> list[SplitConfig]: ...
    def get_for_user(self, user_id: str, config_id: str) -> SplitConfig | None: ...
    def get_by_name_for_user(self, user_id: str, name: str) -> SplitConfig | None: ...
    def add(self, config: SplitConfig) -> None: ...
    def delete(self, config: SplitConfig) -> None: ...


class SqlAlchemySplitConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: str) -> list[SplitConfig]:
        stmt = select(SplitConfig).where(SplitConfig.user_id == user_id).order_by(SplitConfig.name)
        return list(self._session.execute(stmt).scalars())

    def get_for_user(self, user_id: str, config_id: str) -> SplitConfig | None:
        stmt = select(SplitConfig).where(
            SplitConfig.id == config_id, SplitConfig.user_id == user_id
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_name_for_user(self, user_id: str, name: str) -> SplitConfig | None:
        # Name uniqueness is case-sensitive (docs/SPLIT-CONFIGS-PLAN.md O6) —
        # unlike Tag.name's case-insensitive get-or-create, a split config's
        # name is a user-chosen label the owner types and re-types verbatim
        # when saving/overwriting, not a shared free-text vocabulary.
        stmt = select(SplitConfig).where(SplitConfig.user_id == user_id, SplitConfig.name == name)
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, config: SplitConfig) -> None:
        self._session.add(config)

    def delete(self, config: SplitConfig) -> None:
        self._session.delete(config)
