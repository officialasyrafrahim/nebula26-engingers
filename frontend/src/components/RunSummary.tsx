import type { PlanningRun } from "../api/types";
import { formatDate, formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface RunSummaryProps {
  run: PlanningRun;
}

const COUNT_LABELS: Record<string, string> = {
  lines: "Lines",
  stations: "Stations",
  sectors: "Sectors",
  locations: "Locations",
  buffer_rules: "Buffer rules",
  contracts: "Contracts",
  activities: "Activities",
};

export default function RunSummary({ run }: RunSummaryProps) {
  const summary = run.parse_summary ?? {
    files: [],
    counts: {},
    horizon_start: null,
    horizon_weeks: null,
    issues: [],
  };
  const counts = summary.counts ?? {};
  const keys = Object.keys(COUNT_LABELS).filter((key) => key in counts);
  const ok = run.parse_status === "OK";

  return (
    <Panel
      title="Parse summary"
      eyebrow={`Stage 2 · Inspect · run ${run.id.slice(0, 8)}`}
      tone={ok ? "ok" : "danger"}
      actions={
        <span className="gate-inline">
          <SignalLamp tone={ok ? "ok" : "danger"} size="sm" label={run.parse_status} />
          <span>{run.parse_status}</span>
        </span>
      }
    >
      <dl className="metrics">
        <div className="metrics__cell">
          <dt>Horizon start</dt>
          <dd>{formatDate(run.horizon_start ?? summary.horizon_start)}</dd>
        </div>
        <div className="metrics__cell">
          <dt>Horizon weeks</dt>
          <dd>{formatNumber(run.horizon_weeks ?? summary.horizon_weeks)}</dd>
        </div>
        <div className="metrics__cell">
          <dt>Files accepted</dt>
          <dd>{summary.files?.length ?? 0} / 8</dd>
        </div>
      </dl>

      {keys.length > 0 ? (
        <ul className="counts" aria-label="Parsed record counts">
          {keys.map((key) => (
            <li key={key} className="counts__cell">
              <span className="counts__value">{formatNumber(counts[key])}</span>
              <span className="counts__label">{COUNT_LABELS[key]}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {summary.issues && summary.issues.length > 0 ? (
        <div className="notice notice--warn" role="status">
          <span className="notice__title">Parse notes</span>
          <ul className="notice__list">
            {summary.issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}
