import type { CSSProperties } from "react";

import type {
  Activity,
  ScheduleAccess,
  ScheduleOccupancy,
} from "../api/types";
import {
  effectiveNight,
  nightSourceLabel,
  nightSourceOf,
  type ActivitySelection,
} from "../lib/schematic";
import { formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ActivityTimelineProps {
  access: ScheduleAccess[];
  activities: Activity[];
  occupancy?: ScheduleOccupancy[];
  selectedActivityId?: string | null;
  onSelect?: (selection: ActivitySelection) => void;
}

function hueFor(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) % 360;
  }
  return hash;
}

function shortLocation(locationId: string): string {
  const parts = locationId.split(":");
  return parts.length > 2 ? parts.slice(2).join(":") : locationId;
}

export default function ActivityTimeline({
  access,
  activities,
  occupancy = [],
  selectedActivityId = null,
  onSelect,
}: ActivityTimelineProps) {
  const contractByActivity = new Map(
    activities.map((activity) => [activity.activity_id, activity.contract_number]),
  );

  const occupancyByActivityWeek = new Map<
    string,
    { locations: string[]; groups: string[] }
  >();
  for (const row of occupancy) {
    const key = `${row.activity_id}::${row.week}`;
    const entry = occupancyByActivityWeek.get(key) ?? {
      locations: [],
      groups: [],
    };
    if (!entry.locations.includes(row.location_id)) {
      entry.locations.push(row.location_id);
    }
    if (row.co_share_group && !entry.groups.includes(row.co_share_group)) {
      entry.groups.push(row.co_share_group);
    }
    occupancyByActivityWeek.set(key, entry);
  }

  const byWeek = new Map<number, ScheduleAccess[]>();
  for (const row of access) {
    const bucket = byWeek.get(row.week) ?? [];
    bucket.push(row);
    byWeek.set(row.week, bucket);
  }
  const weeks = [...byWeek.keys()].sort((a, b) => a - b);
  const totalEclo = access.filter((row) => row.eclo).length;
  const nightSource = nightSourceOf(access);

  return (
    <Panel
      title="Activity access timeline"
      eyebrow={`Weeks from horizon start · ${nightSourceLabel(nightSource)} · ECLO flagged`}
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
                    const occupancyEntry = occupancyByActivityWeek.get(
                      `${row.activity_id}::${row.week}`,
                    );
                    const locations = occupancyEntry?.locations ?? [];
                    const groups = occupancyEntry?.groups ?? [];
                    const primaryLocation = locations[0];
                    const selected = selectedActivityId === row.activity_id;
                    return (
                      <li key={row.id} className="timeline__chip-wrap">
                        <button
                          type="button"
                          className={`access-chip${row.eclo ? " access-chip--eclo" : ""}${
                            selected ? " access-chip--selected" : ""
                          }`}
                          style={{ "--chip-hue": hueFor(contract) } as CSSProperties}
                          title={`${row.activity_id} seq ${row.access_seq} · week ${row.week} · night ${effectiveNight(row)} (${nightSourceLabel(nightSource)})${row.eclo ? " · ECLO" : ""}`}
                          onClick={
                            onSelect
                              ? () =>
                                  onSelect({
                                    activityId: row.activity_id,
                                    week: row.week,
                                    night: effectiveNight(row),
                                  })
                              : undefined
                          }
                        >
                          <span className="access-chip__id">{row.activity_id}</span>
                          <span className="access-chip__seq">#{row.access_seq}</span>
                          <span className="access-chip__night">
                            n{effectiveNight(row)}
                          </span>
                          {primaryLocation ? (
                            <span
                              className="access-chip__loc"
                              title={`Occupancy ${locations.join(", ")}`}
                            >
                              {shortLocation(primaryLocation)}
                              {locations.length > 1 ? ` +${locations.length - 1}` : ""}
                            </span>
                          ) : null}
                          {groups.length > 0 ? (
                            <span
                              className="access-chip__group"
                              title={`Co-share group ${groups.join(", ")}`}
                            >
                              [{groups.join(",")}]
                            </span>
                          ) : null}
                          {row.eclo ? (
                            <SignalLamp tone="warn" size="sm" label="ECLO access" />
                          ) : null}
                        </button>
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
