// Pure projections of the network and schedule into the control-board
// schematic. Nothing here re-derives solver decisions; it only reshapes the
// server payloads into ordered track nodes and overlay lookups.

import type {
  ActivitySpan,
  NetworkResponse,
  ScheduleAccess,
  ScheduleOccupancy,
} from "../api/types";

export interface ActivitySelection {
  activityId: string;
  week: number | null;
  night: number | null;
}

export type NightSource = "physical" | "local" | "mixed";

export interface SchematicNode {
  key: string;
  kind: "station" | "sector";
  label: string;
  locationId: string;
  seq: number;
  isInterchange: boolean;
  isShared: boolean;
}

export interface SchematicBound {
  bound: string;
  nodes: SchematicNode[];
}

export interface SchematicLine {
  lineCode: string;
  lineName: string;
  bounds: SchematicBound[];
}

export interface PossessionMember {
  activityId: string;
  night: number | null;
  eclo: boolean;
}

export interface CoShareGrouping {
  group: string;
  members: PossessionMember[];
}

export type SpanLayer = "buffer" | "mirror" | "interchange";

export interface SpanOverlays {
  available: boolean;
  byLocation: Map<string, Set<SpanLayer>>;
  byActivity: Map<string, ActivitySpan>;
}

export type CapacityStatus = "ok" | "blocked" | "excess-soft" | "elastic" | "hard";

export interface CapacityReading {
  locationId: string;
  week: number;
  used: number;
  capacity: number;
  excess: number;
  status: CapacityStatus;
}

export interface CoShareMember {
  activityId: string;
  night: number | null;
}

export interface ActivityGroupMembership {
  locationId: string;
  week: number;
  group: string;
  members: CoShareMember[];
}

export interface AccessSummary {
  scheduled: number;
  eclo: number;
  yieldUnits: number;
  rows: ScheduleAccess[];
}

const BOUND_RANK: Record<string, number> = { EB: 0, WB: 1 };

function boundRank(bound: string): number {
  return BOUND_RANK[bound] ?? 99;
}

export function shortLocation(locationId: string): string {
  const parts = locationId.split(":");
  if (parts.length >= 3) return `${parts[2]}·${parts[parts.length - 1]}`;
  return locationId;
}

// The internal physical slot is the honest night key when the API publishes it.
// When it is absent the local access_night is used and must be labelled local.
export function effectiveNight(row: ScheduleAccess): number {
  return row.physical_night ?? row.access_night;
}

export function nightSourceOf(access: ScheduleAccess[]): NightSource {
  let physical = 0;
  let local = 0;
  for (const row of access) {
    if (row.physical_night != null) physical += 1;
    else local += 1;
  }
  if (physical > 0 && local > 0) return "mixed";
  return physical > 0 ? "physical" : "local";
}

export function nightSourceLabel(source: NightSource): string {
  switch (source) {
    case "physical":
      return "physical night";
    case "mixed":
      return "physical night where published, otherwise contract-local night";
    default:
      return "contract-local night index";
  }
}

export function buildSchematic(network: NetworkResponse): SchematicLine[] {
  const stations = network.stations ?? [];
  const sectors = network.sectors ?? [];
  const locations = network.locations ?? [];

  return (network.lines ?? []).map((line) => {
    const lineStations = stations
      .filter((station) => station.line_code === line.line_code)
      .sort((left, right) => left.seq - right.seq);
    const lineSectors = sectors.filter(
      (sector) => sector.line_code === line.line_code,
    );
    const bounds = [
      ...new Set(
        locations
          .filter((location) => location.line_code === line.line_code)
          .map((location) => location.bound),
      ),
    ].sort((left, right) => boundRank(left) - boundRank(right));

    const schematicBounds = bounds.map((bound) => {
      const nodes: SchematicNode[] = [];
      for (let index = 0; index < lineStations.length; index += 1) {
        const station = lineStations[index];
        nodes.push({
          key: `PLAT:${line.line_code}:${station.station_id}:${bound}`,
          kind: "station",
          label: station.station_id,
          locationId: `PLAT:${line.line_code}:${station.station_id}:${bound}`,
          seq: station.seq,
          isInterchange: station.is_interchange,
          isShared: false,
        });
        const next = lineStations[index + 1];
        if (!next) continue;
        const sector = lineSectors.find(
          (candidate) =>
            (candidate.from_station_id === station.station_id &&
              candidate.to_station_id === next.station_id) ||
            (candidate.from_station_id === next.station_id &&
              candidate.to_station_id === station.station_id),
        );
        if (sector) {
          nodes.push({
            key: `${sector.sector_id}:${bound}`,
            kind: "sector",
            label: `${sector.from_station_id}–${sector.to_station_id}`,
            locationId: `${sector.sector_id}:${bound}`,
            seq: sector.seq,
            isInterchange: false,
            isShared: sector.is_shared,
          });
        }
      }
      return { bound, nodes };
    });

    return {
      lineCode: line.line_code,
      lineName: line.line_name,
      bounds: schematicBounds,
    };
  });
}

export function scheduledWeeks(access: ScheduleAccess[]): number[] {
  return [...new Set(access.map((row) => row.week))].sort(
    (left, right) => left - right,
  );
}

export function nightsForWeek(access: ScheduleAccess[], week: number): number[] {
  return [
    ...new Set(
      access.filter((row) => row.week === week).map((row) => effectiveNight(row)),
    ),
  ].sort((left, right) => left - right);
}

export function activeActivityIds(
  access: ScheduleAccess[],
  week: number | null,
  night: number | null,
): Set<string> {
  const ids = new Set<string>();
  for (const row of access) {
    if (week != null && row.week !== week) continue;
    if (night != null && effectiveNight(row) !== night) continue;
    ids.add(row.activity_id);
  }
  return ids;
}

export function occupancyForWeek(
  occupancy: ScheduleOccupancy[],
  access: ScheduleAccess[],
  week: number,
  night: number | null,
): Map<string, CoShareGrouping[]> {
  const accessByActivity = new Map<string, ScheduleAccess>();
  for (const row of access) {
    if (row.week === week) accessByActivity.set(row.activity_id, row);
  }

  const byLocation = new Map<string, Map<string, PossessionMember[]>>();
  for (const row of occupancy) {
    if (row.week !== week) continue;
    const accessRow = accessByActivity.get(row.activity_id);
    const memberNight = accessRow ? effectiveNight(accessRow) : null;
    if (night != null && memberNight !== night) continue;
    const group = row.co_share_group || "—";
    const groups =
      byLocation.get(row.location_id) ?? new Map<string, PossessionMember[]>();
    const members = groups.get(group) ?? [];
    if (!members.some((member) => member.activityId === row.activity_id)) {
      members.push({
        activityId: row.activity_id,
        night: memberNight,
        eclo: accessRow?.eclo ?? false,
      });
    }
    groups.set(group, members);
    byLocation.set(row.location_id, groups);
  }

  const result = new Map<string, CoShareGrouping[]>();
  for (const [locationId, groups] of byLocation) {
    result.set(
      locationId,
      [...groups.entries()]
        .map(([group, members]) => ({
          group,
          members: [...members].sort((left, right) =>
            left.activityId.localeCompare(right.activityId),
          ),
        }))
        .sort((left, right) => left.group.localeCompare(right.group)),
    );
  }
  return result;
}

export function locationCapacity(
  network: NetworkResponse,
  locationId: string,
): number {
  const mapped = network.location_capacities?.[locationId];
  if (mapped != null) return mapped;
  const supply = network.locations?.find(
    (location) => location.location_id === locationId,
  );
  return supply?.supply_capacity ?? 0;
}

export function capacityStatus(
  used: number,
  capacity: number,
  scenario: string,
): CapacityStatus {
  const excess = Math.max(0, used - capacity);
  if (excess === 0) return "ok";
  if (scenario === "A") return "blocked";
  if (scenario === "C") return excess <= 1 ? "elastic" : "hard";
  return "excess-soft";
}

export function capacityReading(
  network: NetworkResponse,
  occupancy: ScheduleOccupancy[],
  locationId: string,
  week: number,
  scenario: string,
): CapacityReading {
  const groups = new Set<string>();
  for (const row of occupancy) {
    if (row.week !== week || row.location_id !== locationId) continue;
    groups.add(row.co_share_group || "—");
  }
  const used = groups.size;
  const capacity = locationCapacity(network, locationId);
  return {
    locationId,
    week,
    used,
    capacity,
    excess: Math.max(0, used - capacity),
    status: capacityStatus(used, capacity, scenario),
  };
}

export function spanOverlays(
  network: NetworkResponse,
  activityIds: Iterable<string>,
): SpanOverlays {
  const spans = network.activity_spans;
  if (!spans || Object.keys(spans).length === 0) {
    return { available: false, byLocation: new Map(), byActivity: new Map() };
  }

  const byLocation = new Map<string, Set<SpanLayer>>();
  const byActivity = new Map<string, ActivitySpan>();
  const add = (locationId: string, layer: SpanLayer) => {
    const layers = byLocation.get(locationId) ?? new Set<SpanLayer>();
    layers.add(layer);
    byLocation.set(locationId, layers);
  };

  for (const activityId of activityIds) {
    const span = spans[activityId];
    if (!span) continue;
    byActivity.set(activityId, span);
    // A closure with no buffer extension repeats the occupied route exactly.
    // Occupied cells already carry the possession, so the safety-buffer layer
    // must skip them rather than paint a buffer on the activity's own route.
    const occupied = new Set(span.occupied_locations ?? []);
    for (const locationId of span.closure_locations ?? []) {
      if (!occupied.has(locationId)) add(locationId, "buffer");
    }
    for (const locationId of span.mirrored_locations ?? []) add(locationId, "mirror");
    for (const locationId of span.interchange_locations ?? []) {
      add(locationId, "interchange");
    }
  }

  return { available: true, byLocation, byActivity };
}

// The line code is the second segment of every location id, for example
// ``SEC:ALP:H01_H02:EB`` or ``PLAT:BET:H01:WB``.
export function lineOfLocation(locationId: string | null | undefined): string | null {
  if (!locationId) return null;
  const parts = locationId.split(":");
  return parts.length >= 2 && parts[1] ? parts[1] : null;
}

// Every line an activity actually touches. The occupied route supplies the own
// line; a Live activity that triggers the H01-H02 interchange also reaches the
// other line through its compiled interchange closures. ECLO continuity is per
// line, and a cross-line Live ECLO must satisfy both windows, so both lines are
// counted here instead of only the activity's start location.
export function linesForActivity(
  network: NetworkResponse,
  activityId: string,
): string[] {
  const lines = new Set<string>();
  const span = network.activity_spans?.[activityId];
  const occupied = span?.occupied_locations?.length
    ? span.occupied_locations
    : (network.routes?.[activityId] ?? []);
  for (const locationId of occupied) {
    const line = lineOfLocation(locationId);
    if (line) lines.add(line);
  }
  for (const locationId of span?.interchange_locations ?? []) {
    const line = lineOfLocation(locationId);
    if (line) lines.add(line);
  }
  if (lines.size === 0) {
    const activity = network.activities?.find(
      (entry) => entry.activity_id === activityId,
    );
    for (const locationId of [
      activity?.start_location_id,
      activity?.end_location_id,
    ]) {
      const line = lineOfLocation(locationId);
      if (line) lines.add(line);
    }
  }
  return [...lines].sort();
}

// A possession chip stands for one activity on one location-week. When the
// board is showing all nights the chip's own physical/local night is the honest
// link; only fall back to the board's active night when the member has none.
export function selectionForPossession(
  member: Pick<PossessionMember, "activityId" | "night">,
  week: number,
  activeNight: number | null,
): ActivitySelection {
  return {
    activityId: member.activityId,
    week,
    night: member.night ?? activeNight,
  };
}

// Every location-week with a recorded possession, re-derived from the published
// occupancy and supply table. The validator's capacity_hotspots feed only lists
// location-weeks *above* supply, so this projection is what lets the board show
// a location-week that sits exactly at capacity without inventing values.
export function capacityReadings(
  network: NetworkResponse,
  occupancy: ScheduleOccupancy[],
  scenario: string,
): CapacityReading[] {
  const groupsByLocationWeek = new Map<string, Set<string>>();
  for (const row of occupancy) {
    const key = `${row.location_id}::${row.week}`;
    const groups = groupsByLocationWeek.get(key) ?? new Set<string>();
    groups.add(row.co_share_group || "—");
    groupsByLocationWeek.set(key, groups);
  }

  const readings: CapacityReading[] = [];
  for (const [key, groups] of groupsByLocationWeek) {
    const separator = key.lastIndexOf("::");
    const locationId = key.slice(0, separator);
    const week = Number(key.slice(separator + 2));
    const used = groups.size;
    const capacity = locationCapacity(network, locationId);
    readings.push({
      locationId,
      week,
      used,
      capacity,
      excess: Math.max(0, used - capacity),
      status: capacityStatus(used, capacity, scenario),
    });
  }

  return readings.sort((left, right) =>
    left.week === right.week
      ? left.locationId.localeCompare(right.locationId)
      : left.week - right.week,
  );
}

export function isAtCapacity(reading: CapacityReading): boolean {
  return reading.used > 0 && reading.capacity > 0 && reading.used === reading.capacity;
}

export function accessSummary(
  access: ScheduleAccess[],
  activityId: string,
): AccessSummary {
  const rows = access
    .filter((row) => row.activity_id === activityId)
    .sort((left, right) =>
      left.week === right.week
        ? left.access_seq - right.access_seq
        : left.week - right.week,
    );
  const eclo = rows.filter((row) => row.eclo).length;
  const yieldUnits = rows.reduce((sum, row) => sum + (row.eclo ? 1.5 : 1), 0);
  return { scheduled: rows.length, eclo, yieldUnits, rows };
}

// Co-share membership for the drawer. A co-share group can mix contract-local
// nights, so each member carries its own effective night rather than inheriting
// the selected activity's night. The caller falls back to the group/board night
// only when a member genuinely has no recorded night.
export function coShareMemberships(
  occupancy: ScheduleOccupancy[],
  access: ScheduleAccess[],
  activityId: string,
  week: number | null,
): ActivityGroupMembership[] {
  const nightByActivityWeek = new Map<string, number>();
  for (const row of access) {
    const key = `${row.activity_id}::${row.week}`;
    if (!nightByActivityWeek.has(key)) {
      nightByActivityWeek.set(key, effectiveNight(row));
    }
  }

  const mine = occupancy.filter(
    (row) =>
      row.activity_id === activityId && (week == null || row.week === week),
  );
  const seen = new Set<string>();
  const memberships: ActivityGroupMembership[] = [];
  for (const row of mine) {
    const group = row.co_share_group || "—";
    const key = `${row.location_id}::${row.week}::${group}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const members: CoShareMember[] = [
      ...new Set(
        occupancy
          .filter(
            (other) =>
              other.location_id === row.location_id &&
              other.week === row.week &&
              (other.co_share_group || "—") === group,
          )
          .map((other) => other.activity_id),
      ),
    ]
      .sort((left, right) => left.localeCompare(right))
      .map((memberId) => ({
        activityId: memberId,
        night: nightByActivityWeek.get(`${memberId}::${row.week}`) ?? null,
      }));
    memberships.push({
      locationId: row.location_id,
      week: row.week,
      group,
      members,
    });
  }
  return memberships;
}

export function activityCapacityReadings(
  network: NetworkResponse,
  occupancy: ScheduleOccupancy[],
  scenario: string,
  activityId: string,
  week: number | null,
): CapacityReading[] {
  const seen = new Set<string>();
  const readings: CapacityReading[] = [];
  for (const row of occupancy) {
    if (row.activity_id !== activityId) continue;
    if (week != null && row.week !== week) continue;
    const key = `${row.location_id}::${row.week}`;
    if (seen.has(key)) continue;
    seen.add(key);
    readings.push(
      capacityReading(network, occupancy, row.location_id, row.week, scenario),
    );
  }
  return readings.sort((left, right) =>
    left.week === right.week
      ? left.locationId.localeCompare(right.locationId)
      : left.week - right.week,
  );
}
