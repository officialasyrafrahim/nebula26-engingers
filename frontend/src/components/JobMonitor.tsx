import type { ScenarioJob } from "../api/types";
import { isActiveJob } from "../api/types";
import { formatDateTime } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface JobMonitorProps {
  job: ScenarioJob | null;
  pollError: string | null;
  cancelling: boolean;
  onCancel: (job: ScenarioJob) => void;
}

const LIFECYCLE = ["QUEUED", "RUNNING", "VALIDATING"] as const;

function lifecycleIndex(state: string): number {
  const index = LIFECYCLE.indexOf(state as (typeof LIFECYCLE)[number]);
  return index;
}

function stateTone(state: string): "ok" | "warn" | "danger" | "info" | "idle" {
  switch (state) {
    case "COMPLETED":
      return "ok";
    case "QUEUED":
      return "warn";
    case "RUNNING":
    case "VALIDATING":
      return "info";
    case "FAILED":
    case "INFEASIBLE":
    case "TIMED_OUT":
    case "CANCELLED":
      return "danger";
    default:
      return "idle";
  }
}

function terminalMessage(job: ScenarioJob): string | null {
  if (job.error) return job.error;
  const result = job.result;
  if (result && Array.isArray(result.infeasibility_reasons)) {
    const reasons = result.infeasibility_reasons as string[];
    if (reasons.length > 0) return reasons.join("; ");
  }
  if (job.state === "CANCELLED") return "Cancelled before completion.";
  return null;
}

export default function JobMonitor({
  job,
  pollError,
  cancelling,
  onCancel,
}: JobMonitorProps) {
  if (!job) {
    return (
      <Panel title="Job monitor" eyebrow="Stage 3 · Optimise" tone="default">
        <p className="empty">
          No scenario job tracked. Dispatch a scenario to watch its lifecycle.
        </p>
      </Panel>
    );
  }

  const index = lifecycleIndex(job.state);
  const terminal = !isActiveJob(job.state);
  const message = terminal ? terminalMessage(job) : null;

  return (
    <Panel
      title={`Job monitor · ${job.scenario}`}
      eyebrow={`Stage 3 · Optimise · ${job.id.slice(0, 8)}`}
      tone={job.state === "COMPLETED" ? "ok" : terminal ? "danger" : "default"}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={stateTone(job.state)}
            size="sm"
            pulse={isActiveJob(job.state)}
            label={`Job ${job.state}`}
          />
          <span>{job.state}</span>
        </span>
      }
    >
      <ol className="lifecycle" aria-label="Job lifecycle">
        {LIFECYCLE.map((stage, stageIdx) => {
          const reached = index >= stageIdx;
          const current = job.state === stage;
          const done = reached && !current;
          return (
            <li
              key={stage}
              className={`lifecycle__step${reached ? " lifecycle__step--reached" : ""}${
                current ? " lifecycle__step--current" : ""
              }${done ? " lifecycle__step--done" : ""}`}
            >
              <span className="lifecycle__node" aria-hidden="true" />
              <span className="lifecycle__label">{stage}</span>
            </li>
          );
        })}
        <li
          className={`lifecycle__step lifecycle__step--terminal${
            terminal ? " lifecycle__step--reached" : ""
          }`}
        >
          <span className="lifecycle__node" aria-hidden="true" />
          <span className="lifecycle__label">
            {terminal ? job.state : "TERMINAL"}
          </span>
        </li>
      </ol>

      <dl className="metrics">
        <div className="metrics__cell">
          <dt>Submitted</dt>
          <dd>{formatDateTime(job.submitted_at)}</dd>
        </div>
        <div className="metrics__cell">
          <dt>Started</dt>
          <dd>{formatDateTime(job.started_at)}</dd>
        </div>
        <div className="metrics__cell">
          <dt>Finished</dt>
          <dd>{formatDateTime(job.finished_at)}</dd>
        </div>
        <div className="metrics__cell">
          <dt>Time limit</dt>
          <dd>{job.time_limit_seconds ?? "default"}s</dd>
        </div>
        <div className="metrics__cell">
          <dt>Seed</dt>
          <dd>{job.seed ?? "default"}</dd>
        </div>
      </dl>

      {pollError ? (
        <div className="notice notice--warn" role="status">
          <span className="notice__title">Polling interrupted</span>
          <p>{pollError} — retrying.</p>
        </div>
      ) : null}

      {message ? (
        <div
          className={`notice ${job.state === "COMPLETED" ? "notice--ok" : "notice--danger"}`}
          role="status"
        >
          <span className="notice__title">
            {job.state === "COMPLETED" ? "Solve complete" : job.state}
          </span>
          <p>{message}</p>
        </div>
      ) : null}

      {job.result && job.state === "COMPLETED" ? (
        <ul className="counts counts--wide" aria-label="Solve result summary">
          {typeof job.result.access_count === "number" ? (
            <li className="counts__cell">
              <span className="counts__value">{job.result.access_count}</span>
              <span className="counts__label">Access placements</span>
            </li>
          ) : null}
          {typeof job.result.occupancy_count === "number" ? (
            <li className="counts__cell">
              <span className="counts__value">{job.result.occupancy_count}</span>
              <span className="counts__label">Occupancy rows</span>
            </li>
          ) : null}
          {typeof job.result.contract_count === "number" ? (
            <li className="counts__cell">
              <span className="counts__value">{job.result.contract_count}</span>
              <span className="counts__label">Contracts scored</span>
            </li>
          ) : null}
          {typeof job.result.horizon_weeks_used === "number" ? (
            <li className="counts__cell">
              <span className="counts__value">{job.result.horizon_weeks_used}</span>
              <span className="counts__label">Horizon weeks used</span>
            </li>
          ) : null}
        </ul>
      ) : null}

      {isActiveJob(job.state) ? (
        <div className="panel__footer">
          <p className="panel__hint" role="status" aria-live="polite">
            Polling {job.state.toLowerCase()} state…
          </p>
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => onCancel(job)}
            disabled={cancelling}
          >
            {cancelling ? "Cancelling…" : "Cancel job"}
          </button>
        </div>
      ) : null}
    </Panel>
  );
}
