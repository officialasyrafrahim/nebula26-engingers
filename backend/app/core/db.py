"""Database engine, base class and session dependency."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
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

_PHYSICAL_NIGHT_DDL = (
    "ALTER TABLE schedule_access_rows ADD COLUMN physical_night INTEGER"
)
_DUPLICATE_ERROR_MARKERS = (
    "duplicate column",
    "duplicate_column",
    "already exists",
    "already_exists",
)


def _is_duplicate_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _DUPLICATE_ERROR_MARKERS)


def _ensure_physical_night(bind: Engine) -> None:
    """Add the nullable ``physical_night`` column to pre-``v0.3.0`` volumes.

    The API and the worker both call ``initialize_database`` on startup, so the
    alter can race. It is attempted unconditionally and a duplicate-column or
    duplicate-constraint error from a concurrent starter is swallowed. An
    inspect-then-alter is deliberately avoided because it is not atomic with the
    alter and would still allow both starters to issue the DDL.
    """

    try:
        with bind.begin() as connection:
            connection.execute(text(_PHYSICAL_NIGHT_DDL))
    except (OperationalError, ProgrammingError) as exc:
        if not _is_duplicate_error(exc):
            raise


def initialize_database(bind: Engine = engine) -> None:
    """Create current tables and apply the supported additive schema upgrade."""

    Base.metadata.create_all(bind=bind)
    _ensure_physical_night(bind)


def get_db() -> Iterator[Session]:
    """Yield a database session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
