"""Compatibility checks for startup-managed database schema changes."""

from sqlalchemy import create_engine, inspect, text

from app.core.db import initialize_database


def test_initialize_database_adds_nullable_physical_night_to_existing_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE schedule_access_rows (
                    id VARCHAR PRIMARY KEY,
                    access_night INTEGER NOT NULL
                )
                """
            )
        )

    initialize_database(engine)

    columns = {
        column["name"]: column for column in inspect(engine).get_columns(
            "schedule_access_rows"
        )
    }
    assert "physical_night" in columns
    assert columns["physical_night"]["nullable"] is True


def test_initialize_database_is_idempotent_when_column_already_exists():
    """A second starter (or an already-upgraded volume) must not crash.

    Concurrent API and worker startups both run the additive upgrade. The
    duplicate-column path is exercised by calling initialize twice, and again
    against a table that already carries the column.
    """

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE schedule_access_rows (
                    id VARCHAR PRIMARY KEY,
                    access_night INTEGER NOT NULL,
                    physical_night INTEGER
                )
                """
            )
        )

    initialize_database(engine)
    initialize_database(engine)

    columns = {
        column["name"]: column for column in inspect(engine).get_columns(
            "schedule_access_rows"
        )
    }
    assert "physical_night" in columns
    assert columns["physical_night"]["nullable"] is True
