import type { PlanningRun } from "../api/types";
import { formatDateTime, formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface RunLibraryProps {
  runs: PlanningRun[];
  selectedRunId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (run: PlanningRun) => void;
  onRefresh: () => void;
}

export default function RunLibrary({
  runs,
  selectedRunId,
  loading,
  error,
  onSelect,
  onRefresh,
}: RunLibraryProps) {
  return (
    <Panel
      title="Run library"
      eyebrow="Recent planning runs"
      actions={
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      }
    >
      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Could not load runs</span>
          <p>{error}</p>
        </div>
      ) : null}

      {runs.length === 0 && !loading ? (
        <p className="empty">No planning runs yet. Compile an instance to begin.</p>
      ) : null}

      <ul className="runlist" aria-label="Planning runs, newest first">
        {runs.map((run) => {
          const active = run.id === selectedRunId;
          const ok = run.parse_status === "OK";
          const counts = run.parse_summary?.counts ?? {};
          return (
            <li key={run.id}>
              <button
                type="button"
                className={`runlist__item${active ? " runlist__item--active" : ""}`}
                onClick={() => onSelect(run)}
                aria-pressed={active}
              >
                <SignalLamp
                  tone={ok ? "ok" : "danger"}
                  size="sm"
                  label={`Parse status ${run.parse_status}`}
                />
                <span className="runlist__main">
                  <span className="runlist__name">
                    {run.name ?? `Run ${run.id.slice(0, 8)}`}
                  </span>
                  <span className="runlist__meta">
                    {formatDateTime(run.created_at)} · horizon{" "}
                    {formatNumber(run.horizon_weeks)} wks from{" "}
                    {run.horizon_start ?? "—"}
                  </span>
                </span>
                <span className="runlist__counts">
                  <span>{formatNumber(counts.activities)} activities</span>
                  <span>{formatNumber(counts.contracts)} contracts</span>
                  <span>{formatNumber(counts.locations)} locations</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
