"""Shared pytest fixtures for the Rail Access Optimisation backend."""

import os

os.environ["RAO_DATABASE_URL"] = "sqlite://"
os.environ["RAO_START_INPROCESS_WORKER"] = "false"
os.environ["RAO_QUEUE_BACKEND"] = "memory"

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
def session_factory(engine):
    """Return a sessionmaker bound to the test engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory) -> Iterator[Session]:
    """Yield a session bound to the test engine, closed afterwards."""

    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_queue():
    """Clear the process-wide queue singleton between tests."""

    from app.modules.runs import queue as runs_queue

    runs_queue.get_queue.cache_clear()
    yield
    runs_queue.get_queue.cache_clear()


@pytest.fixture()
def worker_session(monkeypatch, db_session):
    """Bind the rail worker's SessionLocal to the test session."""

    from app.workers import rail_solver_worker

    monkeypatch.setattr(rail_solver_worker, "SessionLocal", lambda: db_session)
    return db_session


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """Yield a TestClient whose database dependency is the test session."""

    app = create_app()

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


MINIMAL_INSTANCE_FILES: dict[str, str] = {
    "01_LINES.csv": "line_code,line_name\nALP,Alpha\n",
    "02_STATIONS.csv": (
        "station_id,line_code,seq,is_interchange\n"
        "S01,ALP,1,0\n"
        "S02,ALP,2,0\n"
    ),
    "03_SECTORS.csv": (
        "sector_id,line_code,from_station_id,to_station_id,seq,is_shared\n"
        "SEC:ALP:S01_S02,ALP,S01,S02,1,0\n"
    ),
    "04_LOCATION_SUPPLY.csv": (
        "location_id,location_kind,line_code,bound,supply_capacity\n"
        "PLAT:ALP:S01:EB,platform sector,ALP,EB,4\n"
        "PLAT:ALP:S02:EB,platform sector,ALP,EB,4\n"
        "SEC:ALP:S01_S02:EB,tunnel sector,ALP,EB,4\n"
        "PLAT:ALP:S01:WB,platform sector,ALP,WB,4\n"
        "PLAT:ALP:S02:WB,platform sector,ALP,WB,4\n"
        "SEC:ALP:S01_S02:WB,tunnel sector,ALP,WB,4\n"
    ),
    "05_BUFFER_LOCATION.csv": (
        "nature_of_works,up_to_buffer_sectors,opposite_bound_required\n"
        "Live,2,1\n"
        "Non-live (Consist),1,0\n"
        "Non-live (Others),0,0\n"
    ),
    "06_PARAMETERS.csv": "key,value\nhorizon_start,2027-01-04\nhorizon_weeks,4\n",
    "07_PROJECT_DETAILS.csv": (
        "contract_number,contract_description,contract_award_date,activity_type,"
        "nature_of_activity,contract_priority,contract_completion_date,"
        "planned_completion_date,number_of_workfronts,access_type,"
        "number_of_maximum_access_per_week\n"
        "C1,Test contract,2026-01-01,Renewal,Non-live (Others),3,2027-03-01,"
        "2027-03-01,1,C,3\n"
    ),
    "08_ACTIVITY_DETAILS.csv": (
        "activity_id,contract_number,activity_type,start_location_id,"
        "end_location_id,total_accesses,planned_start_date,"
        "predecessor_activity_id,activity_priority\n"
        "A1,C1,Renewal,SEC:ALP:S01_S02:EB,SEC:ALP:S01_S02:EB,1,2027-01-04,,2\n"
    ),
}


@pytest.fixture()
def minimal_instance_files() -> dict[str, bytes]:
    """The eight minimal instance files as upload bytes."""

    return {
        name: text.encode("utf-8") for name, text in MINIMAL_INSTANCE_FILES.items()
    }


@pytest.fixture()
def public_instance_files() -> dict[str, bytes]:
    """The published public instance files as upload bytes."""

    from app.modules.instance import INSTANCE_FILES
    from tests.helpers_rail import PUBLIC_INSTANCE_DIR

    return {
        name: (PUBLIC_INSTANCE_DIR / name).read_bytes() for name in INSTANCE_FILES
    }


def build_fake_solver_result(
    compiled,
    scenario,
    *,
    status: str = "OPTIMAL",
    feasible: bool = True,
    binding_reasons: dict[str, list[str]] | None = None,
    **kwargs,
):
    """Build a deterministic fake solver result for lifecycle tests."""

    from app.modules.solver.results import (
        AccessPlacement,
        ContractResult,
        OccupancyPlacement,
        SolverResult,
        week_end,
    )

    if not feasible:
        return SolverResult(
            feasible=False,
            scenario=scenario,
            status=status,
            horizon_weeks_used=0,
            objective_breakdown={"scenario": scenario},
            infeasibility_reasons=("stub infeasibility",),
        )

    access: list[AccessPlacement] = []
    occupancy: list[OccupancyPlacement] = []
    last_week = 1
    for activity_id, activity in compiled.activities.items():
        for week in range(1, activity.total_accesses + 1):
            last_week = max(last_week, week)
            access.append(
                AccessPlacement(
                    activity_id=activity_id,
                    access_seq=week,
                    week=week,
                    eclo=False,
                    access_night=1,
                    physical_night=1,
                )
            )
            for location_id in dict.fromkeys(activity.occupied_locations):
                occupancy.append(
                    OccupancyPlacement(
                        activity_id=activity_id,
                        week=week,
                        location_id=location_id,
                        co_share_group="b1",
                    )
                )

    results: list[ContractResult] = []
    for contract_number, contract in sorted(compiled.instance.contracts.items()):
        if not compiled.activities_for_contract(contract_number):
            continue
        simulated = week_end(compiled.instance.horizon_start, last_week)
        results.append(
            ContractResult(
                contract_number=contract_number,
                contract_priority=contract.contract_priority,
                planned_completion_date=contract.planned_completion_date,
                simulated_completion_date=simulated,
                overrun_days=max(0, (simulated - contract.planned_completion_date).days),
                last_week=last_week,
            )
        )

    return SolverResult(
        feasible=True,
        scenario=scenario,
        status=status,
        horizon_weeks_used=last_week,
        access=tuple(access),
        occupancy=tuple(occupancy),
        contract_results=tuple(results),
        contract_completion={
            item.contract_number: item.simulated_completion_date for item in results
        },
        objective_breakdown={"scenario": scenario, "score": 0.0},
        binding_reasons=binding_reasons or {},
    )


@pytest.fixture()
def fake_solver_result():
    """Return the fake solver result builder."""

    return build_fake_solver_result
