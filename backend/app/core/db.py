"""Database engine, base class and session dependency."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _create_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_database(bind: Engine = engine) -> None:
    """Create current tables and apply the supported additive schema upgrade."""

    Base.metadata.create_all(bind=bind)
    columns = {
        column["name"] for column in inspect(bind).get_columns("schedule_access_rows")
    }
    if "physical_night" not in columns:
        with bind.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE schedule_access_rows "
                    "ADD COLUMN physical_night INTEGER"
                )
            )


def get_db() -> Iterator[Session]:
    """Yield a database session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
