import type { PossessionCalendar } from "../api/types";

export function calendarMatches(selected: string, result: string, calendar: PossessionCalendar | null): boolean {
  return selected === result && calendar?.job_id === selected;
}

// Only the official authority may be presented as accepted validation. Any
// other recorded authority, including the bundled fallback, is provisional and
// must be acknowledged before publishing or exporting the calendar.
export function isOfficialAuthority(authority: string | null | undefined): boolean {
  return (authority ?? "").trim().toLowerCase() === "official";
}

export function isProvisionalAuthority(authority: string | null | undefined): boolean {
  return !isOfficialAuthority(authority);
}

export interface CalendarAuthorityBadge {
  provisional: boolean;
  label: string;
  warning: string;
}

export function calendarAuthorityBadge(
  authority: string | null | undefined,
): CalendarAuthorityBadge {
  const provisional = isProvisionalAuthority(authority);
  if (!provisional) {
    return { provisional: false, label: "OFFICIAL", warning: "" };
  }
  return {
    provisional: true,
    label: "PROVISIONAL",
    warning:
      `Provisional: the validator authority is "${authority ?? "unknown"}". ` +
      "This is fallback validation, not official acceptance. Confirm the " +
      "acknowledgement before publishing dates or exporting ICS.",
  };
}


// Opt-in presentation alias set from scripts/mapped_network.py. Raw IDs always remain visible.
const stations: Record<string, Record<string, string>> = {
  ALP: { S01: "Newton", S02: "Little India", S03: "Rochor", S04: "Bugis", H01: "Promenade", H02: "Bayfront", S05: "Downtown", S06: "Telok Ayer", S07: "Chinatown", S08: "Fort Canning" },
  BET: { S11: "Dakota", S12: "Mountbatten", S13: "Stadium", S14: "Nicoll Highway", H01: "Promenade", H02: "Bayfront", S15: "Marina Bay", S16: "Prince Edward Road", S17: "Cantonment", S18: "Keppel" },
};
export function locationLabel(raw: string, mapped: boolean): string {
  if (!mapped) return raw;
  const [kind, line, endpoints, bound] = raw.split(":");
  if (!["SEC", "PLAT"].includes(kind) || !stations[line] || !endpoints) return raw;
  const names = endpoints.split("_").map(id => stations[line][id]);
  if (names.some(name => !name)) return raw;
  return `${line === "ALP" ? "Downtown Line" : "Circle Line"} · ${names.join(" – ")} · ${bound}`;
}

export function compareCalendars(left: PossessionCalendar, right: PossessionCalendar) {
  // Compare observable assignments per activity occurrence, not unstable group UUIDs.
  const occurrences = (calendar: PossessionCalendar) => {
    const byActivity = new Map<string, Set<string>>();
    for (const event of calendar.events) for (const activity of event.activity_ids) {
      const slots = byActivity.get(activity) ?? new Set<string>();
      slots.add(`${event.week}:${event.physical_night}`); byActivity.set(activity, slots);
    }
    return byActivity;
  };
  const l = occurrences(left), r = occurrences(right);
  let unchanged = 0, moved = 0, added = 0, removed = 0;
  for (const id of new Set([...l.keys(), ...r.keys()])) {
    const a = l.get(id) ?? new Set<string>(), b = r.get(id) ?? new Set<string>();
    const same = [...a].filter(slot => b.has(slot)).length;
    unchanged += same; moved += Math.min(a.size - same, b.size - same);
    added += Math.max(0, b.size - a.size); removed += Math.max(0, a.size - b.size);
  }
  const footprints = (calendar: PossessionCalendar) => {
    const groups = new Map<string, Set<string>>();
    for (const e of calendar.events) {
      const identity = JSON.stringify([
        [...e.activity_ids].sort(), [...(e.location_ids ?? [])].sort(),
        [...(e.access_type ?? [])].sort(),
      ]);
      const slots = groups.get(identity) ?? new Set<string>();
      slots.add(`${e.week}:${e.physical_night}`); groups.set(identity, slots);
    }
    return groups;
  };
  const lf = footprints(left), rf = footprints(right);
  let movedPossessions = 0, addedPossessions = 0, removedPossessions = 0;
  for (const id of new Set([...lf.keys(), ...rf.keys()])) {
    const a = lf.get(id) ?? new Set<string>(), b = rf.get(id) ?? new Set<string>();
    const same = [...a].filter(slot => b.has(slot)).length;
    movedPossessions += Math.min(a.size - same, b.size - same);
    addedPossessions += Math.max(0, b.size - a.size);
    removedPossessions += Math.max(0, a.size - b.size);
  }
  return { unchanged, moved, added, removed,
    movedPossessions, addedPossessions, removedPossessions,
    possessionDelta: right.events.length - left.events.length,
    ecloDelta: right.events.filter(e => e.eclo).length - left.events.filter(e => e.eclo).length,
    delayDelta: (right.scores.overrun_days_total ?? 0) - (left.scores.overrun_days_total ?? 0),
    scoreDelta: (right.scores.objective_score ?? 0) - (left.scores.objective_score ?? 0) };
}
