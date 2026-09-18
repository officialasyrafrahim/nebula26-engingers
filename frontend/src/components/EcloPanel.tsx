import type { Activity, ScheduleAccess, ValidatorDetail } from "../api/types";
import { formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface EcloPanelProps {
  access: ScheduleAccess[];
  activities: Activity[];
  detail: ValidatorDetail;
  scenario: string;
}

function lineOf(locationId: string | undefined): string {
  if (!locationId) return "unknown";
  const parts = locationId.split(":");
  return parts.length >= 2 ? parts[1] : "unknown";
}

export default function EcloPanel({
  access,
  activities,
  detail,
  scenario,
}: EcloPanelProps) {
  const lineByActivity = new Map(
    activities.map((activity) => [
      activity.activity_id,
      lineOf(activity.start_location_id),
    ]),
  );

  const ecloRows = access.filter((row) => row.eclo);
  const byLine = new Map<string, ScheduleAccess[]>();
  for (const row of ecloRows) {
    const line = lineByActivity.get(row.activity_id) ?? "unknown";
    const bucket = byLine.get(line) ?? [];
    bucket.push(row);
    byLine.set(line, bucket);
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
