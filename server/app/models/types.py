from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator[datetime]):
    """A DateTime that refuses naive values, in both directions.

    SQLite silently accepts naive datetimes and hands them back naive, which
    would let an accidentally-naive value slip in without SQLAlchemy or the
    DB ever complaining — this decorator makes that a hard error instead.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("TZDateTime requires a timezone-aware datetime")
        return value

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
