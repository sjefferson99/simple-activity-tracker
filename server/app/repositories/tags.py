from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.tag import Tag


class TagRepository(Protocol):
    def get_or_create(self, user_id: str, name: str) -> Tag: ...
    def list_for_user(self, user_id: str) -> list[Tag]: ...
    def get_for_user(self, user_id: str, tag_id: str) -> Tag | None: ...
    def add_to_activity(self, activity: Activity, tag: Tag) -> None: ...
    def remove_from_activity(self, activity: Activity, tag: Tag) -> None: ...
    def delete_all_for_activity(self, activity: Activity) -> None: ...


class SqlAlchemyTagRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self, user_id: str, name: str) -> Tag:
        normalized = name.strip()
        stmt = select(Tag).where(Tag.user_id == user_id)
        existing = {t.name.lower(): t for t in self._session.execute(stmt).scalars()}
        found = existing.get(normalized.lower())
        if found is not None:
            return found
        tag = Tag(user_id=user_id, name=normalized, created_at=datetime.now(UTC))
        self._session.add(tag)
        self._session.flush()
        return tag

    def list_for_user(self, user_id: str) -> list[Tag]:
        stmt = select(Tag).where(Tag.user_id == user_id).order_by(Tag.name)
        return list(self._session.execute(stmt).scalars())

    def get_for_user(self, user_id: str, tag_id: str) -> Tag | None:
        stmt = select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def add_to_activity(self, activity: Activity, tag: Tag) -> None:
        if tag not in activity.tags:
            activity.tags.append(tag)

    def remove_from_activity(self, activity: Activity, tag: Tag) -> None:
        if tag in activity.tags:
            activity.tags.remove(tag)

    def delete_all_for_activity(self, activity: Activity) -> None:
        activity.tags.clear()
