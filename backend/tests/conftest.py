"""Shared pytest fixtures."""

import os

os.environ.setdefault("RMIS_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("RMIS_START_INPROCESS_WORKER", "false")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.main import create_app


@pytest.fixture()
def engine():
    """Create a shared in-memory SQLite engine with all tables."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    """Yield a session bound to the test engine, rolled back afterwards."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """Yield a TestClient with database and settings overrides."""
    app = create_app()

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = get_settings
    with TestClient(app) as test_client:
        yield test_client
