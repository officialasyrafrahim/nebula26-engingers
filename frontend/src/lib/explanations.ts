// Pure reading of the server's explanation evidence. The panel must never
// present a fact as proof of a reason when the value contradicts that reason.
// A false boolean, a zero count or an empty collection is a recorded fact but
// not support, so the reason it is paired with must be reported as unsupported.

export interface ReasonSupport {
  supported: string[];
  unsupported: string[];
}

// Evidence keys each displacement reason code must justify. A code with no
// entry here needs no local facts and is always treated as supported. For codes
// with an entry, at least one key must carry a confirming value; a code whose
// keys are all false/zero/empty is unsupported.
export const REASON_EVIDENCE_KEYS: Record<string, string[]> = {
  BUFFER_CLOSURE: ["buffer_sectors", "closure_location_count"],
  LIVE_MIRROR: ["opposite_bound_required", "mirrored_location_count"],
  INTERCHANGE: ["interchange_location_count"],
  POSSESSION_MIX: ["access_type", "mix_groups"],
  CO_SHARE_PACKED: ["co_share_group", "co_share_partners"],
  CAPACITY: ["capacity_location", "capacity_limit"],
};

export function isConfirmingEvidence(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) && value > 0;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return false;
}

export function reasonSupport(
  evidence: Record<string, unknown>,
  reasonCodes: string[],
): ReasonSupport {
  const supported: string[] = [];
  const unsupported: string[] = [];
  for (const code of reasonCodes) {
    const keys = REASON_EVIDENCE_KEYS[code];
    if (!keys) {
      supported.push(code);
      continue;
    }
    if (keys.some((key) => isConfirmingEvidence(evidence[key]))) {
      supported.push(code);
    } else {
      unsupported.push(code);
    }
  }
  return { supported, unsupported };
}

// The evidence keys tied to the reason codes currently on screen. Used to mark
// facts that sit next to a reason but do not confirm it.
export function reasonEvidenceKeys(reasonCodes: string[]): Set<string> {
  const keys = new Set<string>();
  for (const code of reasonCodes) {
    for (const key of REASON_EVIDENCE_KEYS[code] ?? []) keys.add(key);
  }
  return keys;
}

export function evidenceIsNeutral(
  key: string,
  value: unknown,
  reasonKeys: ReadonlySet<string>,
): boolean {
  return reasonKeys.has(key) && !isConfirmingEvidence(value);
}

// ------------------------------------------------------------------ displaced

// Human labels for the binding constraints the solver can cite when an earlier
// week is rejected. These name the persisted constraint code truthfully; they
// are only shown when the matching binding detail actually supports it.
export const BINDING_LABELS: Record<string, string> = {
  CAPACITY: "location capacity",
  WEEKLY_CAP: "the contract weekly access cap",
  WORKFRONT: "the contract workfront cap",
  POSSESSION_MIX: "possession mix rules",
  BUFFER_CLOSURE: "a closure safety buffer",
  LIVE_MIRROR: "Live opposite-bound mirroring",
  INTERCHANGE: "an interchange closure",
};

export interface DisplacementReading {
  // The explanation carried any displacement keys at all.
  present: boolean;
  displaced: boolean;
  plannedEarliestWeek: number | null;
  actualFirstWeek: number | null;
  rejectedWeeks: number[];
  bindingWeek: number | null;
  bindingConstraints: string[];
  bindingDetails: Record<string, unknown>;
  supportedConstraints: string[];
  unsupportedConstraints: string[];
  // The evidence is complete and internally consistent, so a cause may be named.
  trustworthy: boolean;
  note: string;
}

export const DISPLACEMENT_EVIDENCE_KEYS = [
  "displaced",
  "planned_earliest_week",
  "actual_first_week",
  "rejected_weeks",
  "binding_week",
  "binding_constraints",
  "binding_details",
] as const;

const DISPLACEMENT_KEYS: readonly string[] = DISPLACEMENT_EVIDENCE_KEYS;

function asWeek(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asWeekList(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is number => typeof item === "number" && Number.isFinite(item))
    .sort((left, right) => left - right);
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function displacementReading(
  evidence: Record<string, unknown>,
): DisplacementReading {
  const present = DISPLACEMENT_KEYS.some((key) => key in evidence);
  const base: DisplacementReading = {
    present,
    displaced: false,
    plannedEarliestWeek: null,
    actualFirstWeek: null,
    rejectedWeeks: [],
    bindingWeek: null,
    bindingConstraints: [],
    bindingDetails: {},
    supportedConstraints: [],
    unsupportedConstraints: [],
    trustworthy: false,
    note: "No displacement evidence is persisted for this activity, so the board cannot say why an earlier week was not used.",
  };
  if (!present) return base;

  const displaced = evidence.displaced === true;
  const plannedEarliestWeek = asWeek(evidence.planned_earliest_week);
  const actualFirstWeek = asWeek(evidence.actual_first_week);
  const rejectedWeeks = asWeekList(evidence.rejected_weeks);
  const bindingWeek = asWeek(evidence.binding_week);
  const bindingConstraints = asStringList(evidence.binding_constraints);
  const bindingDetails =
    evidence.binding_details && typeof evidence.binding_details === "object"
      ? (evidence.binding_details as Record<string, unknown>)
      : {};

  const supportedConstraints: string[] = [];
  const unsupportedConstraints: string[] = [];
  for (const code of bindingConstraints) {
    // A constraint counts as proven only when its persisted detail confirms it.
    if (isConfirmingEvidence(bindingDetails[code])) supportedConstraints.push(code);
    else unsupportedConstraints.push(code);
  }

  const weeksKnown = plannedEarliestWeek != null && actualFirstWeek != null;
  const bindingConsistent =
    bindingWeek == null || rejectedWeeks.includes(bindingWeek);
  const trustworthy =
    displaced &&
    weeksKnown &&
    actualFirstWeek > plannedEarliestWeek &&
    bindingWeek != null &&
    bindingConsistent &&
    supportedConstraints.length > 0;

  let note: string;
  if (!displaced) {
    note =
      weeksKnown && actualFirstWeek === plannedEarliestWeek
        ? "No earlier week was rejected: the first access sits at the earliest week the planned start and any predecessor allow."
        : "The solver did not record a rejected earlier week for this activity. The recorded reason codes are the only causes on file.";
  } else if (trustworthy) {
    note = "The earliest admissible week was blocked, so the first access was displaced later.";
  } else {
    note =
      "The solver reports displacement but the persisted evidence is incomplete or inconsistent, so the board does not name a binding constraint.";
  }

  return {
    present,
    displaced,
    plannedEarliestWeek,
    actualFirstWeek,
    rejectedWeeks,
    bindingWeek,
    bindingConstraints,
    bindingDetails,
    supportedConstraints,
    unsupportedConstraints,
    trustworthy,
    note,
  };
}
