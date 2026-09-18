import type { CSSProperties } from "react";

import type { Activity, ScheduleAccess } from "../api/types";
import { formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ActivityTimelineProps {
  access: ScheduleAccess[];
  activities: Activity[];
}

function hueFor(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) % 360;
  }
  return hash;
}

export default function ActivityTimeline({
  access,
  activities,
}: ActivityTimelineProps) {
  const contractByActivity = new Map(
    activities.map((activity) => [activity.activity_id, activity.contract_number]),
  );

  const byWeek = new Map<number, ScheduleAccess[]>();
  for (const row of access) {
    const bucket = byWeek.get(row.week) ?? [];
    bucket.push(row);
    byWeek.set(row.week, bucket);
  }
  const weeks = [...byWeek.keys()].sort((a, b) => a - b);
  const totalEclo = access.filter((row) => row.eclo).length;

  return (
    <Panel
      title="Activity access timeline"
      eyebrow="Weeks from horizon start · ECLO flagged"
      actions={
        <span className="panel__meter">
          {weeks.length} weeks · {formatNumber(access.length)} accesses · {totalEclo} ECLO
        </span>
      }
    >
      {weeks.length === 0 ? (
        <p className="empty">No access placements in this schedule.</p>
      ) : (
        <div className="timeline">
          {weeks.map((week) => {
            const rows = [...(byWeek.get(week) ?? [])].sort((a, b) =>
              a.activity_id === b.activity_id
                ? a.access_seq - b.access_seq
                : a.activity_id.localeCompare(b.activity_id),
            );
            const ecloCount = rows.filter((row) => row.eclo).length;
            return (
              <div key={week} className="timeline__week">
                <div className="timeline__rail">
                  <span className="timeline__week-tag">W{String(week).padStart(2, "0")}</span>
                  <span className="timeline__week-meta">
                    {rows.length} access{rows.length === 1 ? "" : "es"}
                    {ecloCount > 0 ? ` · ${ecloCount} ECLO` : ""}
                  </span>
                </div>
                <ol className="timeline__track" aria-label={`Week ${week} accesses`}>
                  {rows.map((row) => {
                    const contract = contractByActivity.get(row.activity_id) ?? "";
                    return (
                      <li
                        key={row.id}
                        className={`access-chip${row.eclo ? " access-chip--eclo" : ""}`}
                        style={{ "--chip-hue": hueFor(contract) } as CSSProperties}
                        title={`${row.activity_id} seq ${row.access_seq} · week ${row.week} · night ${row.access_night}${row.eclo ? " · ECLO" : ""}`}
                      >
                        <span className="access-chip__id">{row.activity_id}</span>
                        <span className="access-chip__seq">#{row.access_seq}</span>
                        <span className="access-chip__night">n{row.access_night}</span>
                        {row.eclo ? (
                          <SignalLamp tone="warn" size="sm" label="ECLO access" />
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
