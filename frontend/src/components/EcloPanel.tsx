import type {
  NetworkResponse,
  ScheduleAccess,
  ValidatorDetail,
} from "../api/types";
import { linesForActivity } from "../lib/schematic";
import { formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface EcloPanelProps {
  access: ScheduleAccess[];
  network: NetworkResponse;
  detail: ValidatorDetail;
  scenario: string;
}

export default function EcloPanel({
  access,
  network,
  detail,
  scenario,
}: EcloPanelProps) {
  const ecloRows = access.filter((row) => row.eclo);

  // Count every line the ECLO work actually reaches: the full occupied route
  // plus the other line for a cross-line Live interchange. Using only the
  // activity's start location under-counts Live work that spans H01-H02.
  const linesByActivity = new Map<string, string[]>();
  const linesFor = (activityId: string): string[] => {
    const cached = linesByActivity.get(activityId);
    if (cached) return cached;
    const lines = linesForActivity(network, activityId);
    linesByActivity.set(activityId, lines);
    return lines;
  };

  const byLine = new Map<string, ScheduleAccess[]>();
  for (const row of ecloRows) {
    const lines = linesFor(row.activity_id);
    for (const line of lines.length > 0 ? lines : ["unknown"]) {
      const bucket = byLine.get(line) ?? [];
      bucket.push(row);
      byLine.set(line, bucket);
    }
  }

  const ecloNights = detail.eclo_nights || ecloRows.length;

  return (
    <Panel
      title="ECLO indicators"
      eyebrow={`Scenario ${scenario} · extended close-down operations`}
      tone={ecloRows.length > 0 ? "warn" : "default"}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={ecloRows.length > 0 ? "warn" : "idle"}
            size="sm"
            label={ecloRows.length > 0 ? "ECLO used" : "No ECLO"}
          />
          <span>{formatNumber(ecloNights)} ECLO nights</span>
        </span>
      }
    >
      <ul className="counts" aria-label="ECLO summary">
        <li className="counts__cell">
          <span className="counts__value">{formatNumber(ecloNights)}</span>
          <span className="counts__label">ECLO nights</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{formatNumber(detail.nights_scheduled)}</span>
          <span className="counts__label">Nights scheduled</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{byLine.size}</span>
          <span className="counts__label">Lines touched</span>
        </li>
      </ul>

      {ecloRows.length === 0 ? (
        <p className="empty">
          No ECLO accesses in this schedule. Scenario A forbids ECLO; B and C allow it.
        </p>
      ) : (
        <div className="eclo">
          {[...byLine.entries()].map(([line, rows]) => {
            const weeks = [...new Set(rows.map((row) => row.week))].sort(
              (a, b) => a - b,
            );
            return (
              <div key={line} className="eclo__line">
                <div className="eclo__head">
                  <span className="eclo__code">{line}</span>
                  <span className="eclo__meta">
                    {rows.length} ECLO · weeks {weeks.join(", ")}
                  </span>
                </div>
                <ol className="eclo__cells" aria-label={`ECLO weeks on ${line}`}>
                  {weeks.map((week) => (
                    <li key={week} className="eclo__cell">
                      <span className="eclo__week">W{String(week).padStart(2, "0")}</span>
                      <span className="eclo__count">
                        {rows.filter((row) => row.week === week).length}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
