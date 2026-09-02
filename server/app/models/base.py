from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — every ORM model (added from W1) inherits this,
    so alembic/env.py's target_metadata sees the whole schema for autogenerate."""
