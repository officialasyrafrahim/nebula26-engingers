// Presentation mapping and unavailable-state logic for the optional LTA
// DataMall advisory context.
//
// This is a display and query-key layer only. The solver keeps its canonical
// identifiers and nothing here reaches the solver, validator, scores or the
// published CSVs. A hidden instance whose lines or stations are not in the
// table degrades to an explicit "unavailable for this network" state instead of
// sending a guessed code to LTA.
//
// Source: LTA DataMall static dataset "Train Station Codes and Chinese Names"
// (datamall.lta.gov.sg, Public Transport) and the LTA DataMall API User Guide
// v6.9, sections 2.7, 2.8, 2.11, 2.24 and 2.25. The mapping is an unverified
// presentation layer, consistent with data/mapped/README.md.

import type { DatamallState, NetworkResponse } from "../api/types";

export const DATAMALL_NETWORK_KEY = "dtl-ccl-demo";
export const DATAMALL_ADVISORY_LABEL = "Advisory context, not used in scoring";
export const DATAMALL_UNAVAILABLE_REASON =
  "DataMall context unavailable for this network";
export const DATAMALL_MAPPING_SOURCE_URL =
  "https://datamall.lta.gov.sg/content/datamall/en/static-data.html";
export const DATAMALL_MAPPING_NOTE =
  "Unverified presentation mapping of the public LTA Downtown, Circle and " +
  "Circle Line Extension lines. Solver identifiers stay canonical and only " +
  "public line and station codes are shared with LTA. DataMall reports " +
  "passenger tap volumes and a coarse low/moderate/high crowding band, never " +
  "train capacity or onboard occupancy.";

export interface DatamallStationMapping {
  solverLine: string;
  solverStation: string;
  name: string;
  code: string;
  line: string;
}

export interface NetworkDatamallContext {
  supported: boolean;
  reason: string | null;
  network: string | null;
  solverLines: string[];
  crowdLines: string[];
  stations: DatamallStationMapping[];
  unmapped: string[];
}

const LINE_MAP: Record<string, string> = {
  ALP: "DTL",
  BET: "CCL",
};

const CROWD_LINES: Record<string, string[]> = {
  ALP: ["DTL"],
  BET: ["CCL", "CEL"],
};

interface StationEntry {
  name: string;
  code: string;
  line: string;
}

const STATION_MAP: Record<string, Record<string, StationEntry>> = {
  ALP: {
    S01: { name: "Newton", code: "DT11", line: "DTL" },
    S02: { name: "Little India", code: "DT12", line: "DTL" },
    S03: { name: "Rochor", code: "DT13", line: "DTL" },
    S04: { name: "Bugis", code: "DT14", line: "DTL" },
    H01: { name: "Promenade", code: "DT15", line: "DTL" },
    H02: { name: "Bayfront", code: "DT16", line: "DTL" },
    S05: { name: "Downtown", code: "DT17", line: "DTL" },
    S06: { name: "Telok Ayer", code: "DT18", line: "DTL" },
    S07: { name: "Chinatown", code: "DT19", line: "DTL" },
    S08: { name: "Fort Canning", code: "DT20", line: "DTL" },
  },
  BET: {
    S11: { name: "Dakota", code: "CC8", line: "CCL" },
    S12: { name: "Mountbatten", code: "CC7", line: "CCL" },
    S13: { name: "Stadium", code: "CC6", line: "CCL" },
    S14: { name: "Nicoll Highway", code: "CC5", line: "CCL" },
    H01: { name: "Promenade", code: "CC4", line: "CCL" },
    H02: { name: "Bayfront", code: "CE1", line: "CEL" },
    S15: { name: "Marina Bay", code: "CE2", line: "CEL" },
    S16: { name: "Prince Edward Road", code: "CC32", line: "CCL" },
    S17: { name: "Cantonment", code: "CC31", line: "CCL" },
    S18: { name: "Keppel", code: "CC30", line: "CCL" },
  },
};

export function datamallStation(
  solverLine: string,
  solverStation: string,
): DatamallStationMapping | null {
  const entry = STATION_MAP[solverLine]?.[solverStation];
  if (!entry) return null;
  return {
    solverLine,
    solverStation,
    name: entry.name,
    code: entry.code,
    line: entry.line,
  };
}

// Build the presentation context for a parsed network. The mapping is only
// declared supported when every line and every station has an entry, so a
// hidden instance can never trigger a guessed DataMall query.
export function datamallContextForNetwork(
  network: NetworkResponse,
): NetworkDatamallContext {
  const solverLines = [
    ...new Set((network.lines ?? []).map((line) => line.line_code)),
  ];
  const unmapped: string[] = [];
  for (const line of solverLines) {
    if (!LINE_MAP[line]) unmapped.push(line);
  }

  const stations: DatamallStationMapping[] = [];
  for (const station of network.stations ?? []) {
    const mapped = datamallStation(station.line_code, station.station_id);
    if (!mapped) {
      unmapped.push(`${station.line_code}:${station.station_id}`);
      continue;
    }
    stations.push(mapped);
  }

  const supported = unmapped.length === 0 && solverLines.length > 0;
  const crowdLines = supported
    ? [...new Set(solverLines.flatMap((line) => CROWD_LINES[line] ?? []))]
    : [];

  return {
    supported,
    reason: supported ? null : DATAMALL_UNAVAILABLE_REASON,
    network: supported ? DATAMALL_NETWORK_KEY : null,
    solverLines,
    crowdLines,
    stations,
    unmapped: [...new Set(unmapped)],
  };
}

export function crowdLevelLabel(level: string): string {
  switch (level.toLowerCase()) {
    case "l":
      return "Low";
    case "m":
      return "Moderate";
    case "h":
      return "High";
    default:
      return "Unknown";
  }
}

export type CrowdTone = "ok" | "warn" | "danger" | "idle";

export function crowdLevelTone(level: string): CrowdTone {
  switch (level.toLowerCase()) {
    case "l":
      return "ok";
    case "m":
      return "warn";
    case "h":
      return "danger";
    default:
      return "idle";
  }
}

// A dataset is unavailable when DataMall is off or the last call failed. An
// empty result is available but holds no advisory rows.
export function sourceUnavailable(state: DatamallState): boolean {
  return state === "unconfigured" || state === "error";
}

export function contextUnavailable(context: {
  supported: boolean;
  sources: { state: DatamallState }[];
}): boolean {
  if (!context.supported) return true;
  if (context.sources.length === 0) return true;
  return context.sources.every((source) => sourceUnavailable(source.state));
}
