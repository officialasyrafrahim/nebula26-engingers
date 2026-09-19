// Pure projections for the Tonight controller mode. Everything here is read
// from the persisted schedule and network payloads; nothing is re-derived in the
// browser beyond counting and grouping the published rows.
//
// The night key is the honest one the schedule publishes. When the API exposes
// a physical slot it is shown as an internal planning fact, never as live
// personnel presence. When it is absent the contract-local index is used and
// labelled as local.

import type {
  NetworkResponse,
  ScheduleResponse,
} from "../api/types";
import { locationDisplay } from "./networkNames.ts";
import {
  activeActivityIds,
  capacityReadings,
  effectiveNight,
  isAtCapacity,
  nightSourceOf,
  spanOverlays,
  type NightSource,
} from "./schematic.ts";

export type AttentionKind = "buffer" | "mirror" | "interchange" | "capacity";

export interface TonightWorkfront {
  contractNumber: string;
  contractDescription: string;
  accessType: string;
  nature: string;
  activityIds: string[];
  concurrentWorkfronts: number;
}

export interface TonightAttentionItem {
  kind: AttentionKind;
  locationId: string;
  label: string;
  mapped: boolean;
  activityIds: string[];
  detail: string;
}

export interface TonightHandback {
  activityId: string;
  contractNumber: string;
  week: number;
  night: number | null;
}

export interface TonightSummary {
  week: number;
  night: number | null;
  nightSource: NightSource;
  activityIds: string[];
  workfronts: TonightWorkfront[];
  attention: TonightAttentionItem[];
  finishing: TonightHandback[];
  startingNext: TonightHandback[];
}

const ATTENTION_LABELS: Record<AttentionKind, string> = {
  buffer: "Safety buffer",
  mirror: "Opposite-bound mirror",
  interchange: "Interchange closure",
  capacity: "Capacity limit",
};

export function attentionLabel(kind: AttentionKind): string {
  return ATTENTION_LABELS[kind];
}

function nightForActivity(
  schedule: ScheduleResponse,
  activityId: string,
  week: number | null,
): number | null {
  const rows = schedule.access.filter(
    (row) =>
      row.activity_id === activityId && (week == null || row.week === week),
  );
  if (rows.length === 0) return null;
  return effectiveNight(rows[0]);
}

export function tonightSummary(
  network: NetworkResponse,
  schedule: ScheduleResponse,
  week: number,
  night: number | null,
  scenario: string,
): TonightSummary {
  const ids = activeActivityIds(schedule.access, week, night);
  const activityById = new Map(
    (network.activities ?? []).map((activity) => [activity.activity_id, activity]),
  );

  // Workfronts: the scheduled activities grouped by contract. The contract's
  // own concurrent workfront cap is shown next to what is actually placed.
  const byContract = new Map<string, string[]>();
  for (const activityId of [...ids].sort()) {
    const activity = activityById.get(activityId);
    if (!activity) continue;
    const bucket = byContract.get(activity.contract_number) ?? [];
    bucket.push(activityId);
    byContract.set(activity.contract_number, bucket);
  }
  const workfronts: TonightWorkfront[] = [...byContract.entries()]
    .map(([contractNumber, activityIds]) => {
      const contract = (network.contracts ?? []).find(
        (entry) => entry.contract_number === contractNumber,
      );
      const sample = activityById.get(activityIds[0]);
      return {
        contractNumber,
        contractDescription: contract?.contract_description ?? "—",
        accessType: contract?.access_type ?? sample?.activity_type ?? "—",
        nature: contract?.nature_of_activity ?? "—",
        activityIds,
        concurrentWorkfronts: contract?.number_of_workfronts ?? activityIds.length,
      };
    })
    .sort((left, right) =>
      left.contractNumber.localeCompare(right.contractNumber),
    );

  // Attention items: compiled spans for the activities in view plus the weekly
  // capacity readings. They are grouped by kind and location so a shared
  // location is named once.
  const overlays = spanOverlays(network, ids);
  const attentionMap = new Map<string, TonightAttentionItem>();
  const addAttention = (
    kind: AttentionKind,
    locationId: string,
    activityId: string | null,
    detail: string,
  ) => {
    const display = locationDisplay(locationId);
    const key = `${kind}::${locationId}`;
    const existing = attentionMap.get(key);
    if (existing) {
      if (activityId && !existing.activityIds.includes(activityId)) {
        existing.activityIds.push(activityId);
      }
      return;
    }
    attentionMap.set(key, {
      kind,
      locationId,
      label: display.text,
      mapped: display.mapped,
      activityIds: activityId ? [activityId] : [],
      detail,
    });
  };

  for (const activityId of [...ids].sort()) {
    const span = overlays.byActivity.get(activityId);
    if (!span) continue;
    const occupied = new Set(span.occupied_locations ?? []);
    for (const locationId of span.closure_locations ?? []) {
      if (occupied.has(locationId)) continue;
      addAttention("buffer", locationId, activityId, "Closure safety buffer");
    }
    for (const locationId of span.mirrored_locations ?? []) {
      addAttention("mirror", locationId, activityId, "Live opposite-bound mirror");
    }
    for (const locationId of span.interchange_locations ?? []) {
      addAttention("interchange", locationId, activityId, "Interchange closure");
    }
  }

  // Occupancy is published per week, not per night, so capacity attention is
  // week-level and labelled that way.
  const readings = capacityReadings(network, schedule.occupancy, scenario).filter(
    (reading) =>
      reading.week === week &&
      reading.used > 0 &&
      (reading.status !== "ok" || isAtCapacity(reading)),
  );
  for (const reading of readings) {
    addAttention(
      "capacity",
      reading.locationId,
      null,
      `Week ${reading.week} · ${reading.used}/${reading.capacity} possessions`,
    );
  }

  const kindRank: Record<AttentionKind, number> = {
    capacity: 0,
    buffer: 1,
    mirror: 2,
    interchange: 3,
  };
  const attention = [...attentionMap.values()].sort((left, right) =>
    left.kind === right.kind
      ? left.locationId.localeCompare(right.locationId)
      : kindRank[left.kind] - kindRank[right.kind],
  );

  // Handbacks. "Finishing" is work whose last placed access sits in the
  // selected week (and night when one is filtered). "Starting next" is work
  // whose first access sits in the following week, so the incoming shift knows
  // what it inherits.
  const firstWeek = new Map<string, number>();
  const lastWeek = new Map<string, number>();
  const hasAccessInView = new Map<string, boolean>();
  for (const row of schedule.access) {
    const currentFirst = firstWeek.get(row.activity_id);
    if (currentFirst == null || row.week < currentFirst) {
      firstWeek.set(row.activity_id, row.week);
    }
    const currentLast = lastWeek.get(row.activity_id);
    if (currentLast == null || row.week > currentLast) {
      lastWeek.set(row.activity_id, row.week);
    }
    if (row.week === week && (night == null || effectiveNight(row) === night)) {
      hasAccessInView.set(row.activity_id, true);
    }
  }

  const toHandback = (activityId: string, handbackWeek: number): TonightHandback => {
    const activity = activityById.get(activityId);
    return {
      activityId,
      contractNumber: activity?.contract_number ?? "—",
      week: handbackWeek,
      night: nightForActivity(schedule, activityId, handbackWeek),
    };
  };

  const finishing = [...hasAccessInView.keys()]
    .filter((activityId) => lastWeek.get(activityId) === week)
    .sort()
    .map((activityId) => toHandback(activityId, week));

  const startingNext = [...firstWeek.entries()]
    .filter(([, first]) => first === week + 1)
    .map(([activityId]) => activityId)
    .sort()
    .map((activityId) => toHandback(activityId, week + 1));

  return {
    week,
    night,
    nightSource: nightSourceOf(schedule.access),
    activityIds: [...ids].sort(),
    workfronts,
    attention,
    finishing,
    startingNext,
  };
}
