"""Rail scenario solve worker.

Claims a queued :class:`~app.domain.models.ScenarioJob`, re-parses the eight
stored source files, compiles the instance, solves the scenario, builds the
exact submission bundle, independently validates it, then persists placements,
contract results and the validator report in one transaction. The database is
the authority; the queue is transport only.

Entry point: ``python -m app.workers.rail_solver_worker``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.domain.enums import JobState
from app.domain.models import (
    ContractResultRow,
    PlanningRun,
    ScenarioJob,
    ScheduleAccessRow,
    ScheduleOccupancyRow,
    ValidatorReportRow,
    utcnow,
)
from app.domain.rail.errors import RailDataError
from app.modules.compiler import compile_instance, get_policy
from app.modules.export import (
    SubmissionBundle,
    bundle_from_solver_result,
    write_bundle,
)
from app.modules.instance import INSTANCE_FILES, parse_mapping
from app.modules.instance.service import build_planning_instance
from app.modules.solver import OrToolsUnavailableError, solve
from app.modules.validator import (
    PhysicalWitnessReport,
    ValidatorReport,
    check_physical_witness,
    validate_compiled,
    validate_with_adapter,
)


def _write_instance(source_files: dict, directory: str) -> None:
    root = Path(directory)
    for name in INSTANCE_FILES:
        (root / name).write_text(source_files[name], encoding="utf-8")


def _validate(
    run: PlanningRun, compiled, bundle: SubmissionBundle, scenario: str
) -> ValidatorReport:
    """Validate via the configured official command, else the fallback oracle."""

    command = get_settings().validator_command
    if command:
        with (
            tempfile.TemporaryDirectory() as instance_dir,
            tempfile.TemporaryDirectory() as submission_dir,
        ):
            _write_instance(run.source_files, instance_dir)
            write_bundle(submission_dir, bundle)
            outcome = validate_with_adapter(
                instance_dir, submission_dir, scenario, command=command
            )
        return outcome.report
    return validate_compiled(compiled, bundle, scenario)


def _set_terminal(
    session: Session,
    job_id: uuid.UUID,
    state: JobState,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Roll back and record a terminal job state."""

    session.rollback()
    job = session.get(ScenarioJob, job_id)
    if job is None:
        return
    job.state = state
    job.result = result
    job.error = error
    job.finished_at = utcnow()
    session.commit()


def _persist_success(
    session: Session,
    job: ScenarioJob,
    solver_result,
    report: ValidatorReport,
    physical_checks: PhysicalWitnessReport,
) -> None:
    """Persist placements, contract results and report in one transaction."""

    ready_for_submission = report.ready_for_submission and physical_checks.passed

    session.execute(
        delete(ScheduleAccessRow).where(ScheduleAccessRow.job_id == job.id)
    )
    session.execute(
        delete(ScheduleOccupancyRow).where(ScheduleOccupancyRow.job_id == job.id)
    )
    session.execute(
        delete(ContractResultRow).where(ContractResultRow.job_id == job.id)
    )
    session.execute(
        delete(ValidatorReportRow).where(ValidatorReportRow.job_id == job.id)
    )

    session.add_all(
        ScheduleAccessRow(
            job_id=job.id,
            activity_id=row.activity_id,
            access_seq=row.access_seq,
            week=row.week,
            eclo=bool(row.eclo),
            access_night=row.access_night,
            physical_night=row.physical_night,
        )
        for row in solver_result.access
    )
    session.add_all(
        ScheduleOccupancyRow(
            job_id=job.id,
            activity_id=row.activity_id,
            week=row.week,
            location_id=row.location_id,
            co_share_group=row.co_share_group,
        )
        for row in solver_result.occupancy
    )
    session.add_all(
        ContractResultRow(
            job_id=job.id,
            contract_number=item.contract_number,
            simulated_completion_date=item.simulated_completion_date,
            overrun_days=max(0, int(item.overrun_days)),
        )
        for item in solver_result.contract_results
    )
    session.add(
        ValidatorReportRow(
            job_id=job.id,
            scenario=report.scenario,
            feasible=report.feasible,
            workload_complete=report.workload_complete,
            ready_for_submission=ready_for_submission,
            authority=report.authority,
            report=report.model_dump(mode="json"),
        )
    )

    job.state = JobState.COMPLETED
    job.result = {
        "scenario": solver_result.scenario,
        "status": solver_result.status,
        "horizon_weeks_used": solver_result.horizon_weeks_used,
        "objective_breakdown": solver_result.objective_breakdown,
        "access_count": len(solver_result.access),
        "occupancy_count": len(solver_result.occupancy),
        "contract_count": len(solver_result.contract_results),
        "authority": report.authority,
        "ready_for_submission": ready_for_submission,
        "binding_reasons": solver_result.binding_reasons,
        "physical_checks": physical_checks.model_dump(mode="json"),
    }
    job.error = None
    job.finished_at = utcnow()
    session.commit()


def process_next_job(timeout: float | None = 1.0) -> bool:
    """Claim and process the next queued scenario job."""

    from app.modules.runs.queue import get_queue

    job_id = get_queue().dequeue(timeout)
    if job_id is None:
        return False

    session = SessionLocal()
    try:
        job = session.get(ScenarioJob, job_id)
        if job is None or job.state != JobState.QUEUED:
            return True
        if job.cancel_requested:
            _set_terminal(session, job_id, JobState.CANCELLED)
            return True

        job.state = JobState.RUNNING
        job.started_at = utcnow()
        session.commit()

        run = session.get(PlanningRun, job.run_id)
        if run is None:
            _set_terminal(session, job_id, JobState.FAILED, error="planning run not found")
            return True

        settings = get_settings()
        try:
            instance = build_planning_instance(parse_mapping(run.source_files))
            compiled = compile_instance(instance)
            solver_result = solve(
                compiled,
                job.scenario.value,
                time_limit_seconds=job.time_limit_seconds
                or settings.solver_time_limit_seconds,
                seed=job.seed if job.seed is not None else settings.solver_seed,
                horizon_extension_weeks=settings.horizon_extension_weeks,
            )
        except (RailDataError, OrToolsUnavailableError) as exc:
            _set_terminal(session, job_id, JobState.FAILED, error=str(exc))
            return True
        except Exception as exc:  # pragma: no cover - defensive
            _set_terminal(session, job_id, JobState.FAILED, error=str(exc))
            return True

        if not solver_result.feasible:
            state = (
                JobState.TIMED_OUT
                if solver_result.status == "UNKNOWN"
                else JobState.INFEASIBLE
            )
            _set_terminal(
                session,
                job_id,
                state,
                result={
                    "status": solver_result.status,
                    "infeasibility_reasons": list(solver_result.infeasibility_reasons),
                },
                error=None if state == JobState.INFEASIBLE else "solver timed out",
            )
            return True

        bundle = bundle_from_solver_result(solver_result)
        session.refresh(job)
        if job.cancel_requested:
            _set_terminal(session, job_id, JobState.CANCELLED)
            return True

        job.state = JobState.VALIDATING
        session.commit()

        try:
            report = _validate(run, compiled, bundle, job.scenario.value)
        except Exception as exc:  # pragma: no cover - defensive
            _set_terminal(session, job_id, JobState.FAILED, error=str(exc))
            return True

        session.refresh(job)
        if job.cancel_requested:
            _set_terminal(session, job_id, JobState.CANCELLED)
            return True

        physical_checks = check_physical_witness(
            compiled,
            get_policy(job.scenario.value),
            solver_result.access,
            solver_result.occupancy,
        )
        _persist_success(session, job, solver_result, report, physical_checks)
        return True
    finally:
        session.close()


def run_worker() -> None:
    """Run the worker loop until interrupted."""

    settings = get_settings()
    try:
        while True:
            process_next_job(timeout=settings.worker_poll_seconds)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    run_worker()
