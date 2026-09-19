// Presentation-only mapping from the solver's sandbox identifiers to the real
// DTL/CCL station names documented in data/mapped/README.md.
//
// This layer never feeds logic. Every loader, selection and capacity lookup
// keeps the raw solver identifier; these helpers only choose a display string.
// When an identifier has no entry (a hidden instance, or a new station), the
// raw identifier is returned with mapped=false so the caller can fall back and
// say no mapping is available instead of inventing a name.

export interface NameDisplay {
  text: string;
  mapped: boolean;
}

export interface LineDisplay {
  text: string;
  name: string;
  mapped: boolean;
}

// The mapping is an unverified presentation label, not an operational
// reference. Keep that caveat attached to the surface that shows it.
export const MAPPING_NOTE =
  "Real station names are an unverified presentation mapping of the public " +
  "LTA Downtown and Circle lines. Solver identifiers stay canonical and the " +
  "names never reach the solver.";

const LINE_NAMES: Record<string, { code: string; name: string }> = {
  ALP: { code: "DTL", name: "Downtown Line" },
  BET: { code: "CCL", name: "Circle Line" },
};

// Station names per line code, exactly as documented in data/mapped/README.md.
const STATION_NAMES: Record<string, Record<string, string>> = {
  ALP: {
    S01: "Newton",
    S02: "Little India",
    S03: "Rochor",
    S04: "Bugis",
    H01: "Promenade",
    H02: "Bayfront",
    S05: "Downtown",
    S06: "Telok Ayer",
    S07: "Chinatown",
    S08: "Fort Canning",
  },
  BET: {
    S11: "Dakota",
    S12: "Mountbatten",
    S13: "Stadium",
    S14: "Nicoll Highway",
    H01: "Promenade",
    H02: "Bayfront",
    S15: "Marina Bay",
    S16: "Prince Edward Road",
    S17: "Cantonment",
    S18: "Keppel",
  },
};

export function lineDisplay(lineCode: string): LineDisplay {
  const entry = LINE_NAMES[lineCode];
  if (entry) return { text: entry.code, name: entry.name, mapped: true };
  return { text: lineCode, name: lineCode, mapped: false };
}

export function stationDisplay(lineCode: string, stationId: string): NameDisplay {
  const name = STATION_NAMES[lineCode]?.[stationId];
  if (name) return { text: name, mapped: true };
  return { text: stationId, mapped: false };
}

// A sector id is ``FROM_TO`` for the two stations it joins, for example
// ``S01_S02`` or ``H01_H02``. The mapped label joins the two station names and
// the sector's own identifier is never rewritten.
export function sectorDisplay(lineCode: string, sectorId: string): NameDisplay {
  const parts = sectorId.split("_");
  if (parts.length < 2 || !parts[0] || !parts[1]) {
    return { text: sectorId, mapped: false };
  }
  const from = stationDisplay(lineCode, parts[0]);
  const to = stationDisplay(lineCode, parts[1]);
  return {
    text: `${from.text}–${to.text}`,
    mapped: from.mapped && to.mapped,
  };
}

// Parse a location id such as ``PLAT:ALP:H01:EB`` or ``SEC:ALP:S01_S02:EB``.
// Unknown shapes fall back to the raw id so the board can still show something.
export function locationDisplay(locationId: string): NameDisplay {
  const parts = locationId.split(":");
  if (parts.length >= 3) {
    const [kind, lineCode, target] = parts;
    if (kind === "PLAT") return stationDisplay(lineCode, target);
    if (kind === "SEC") return sectorDisplay(lineCode, target);
  }
  return { text: locationId, mapped: false };
}
