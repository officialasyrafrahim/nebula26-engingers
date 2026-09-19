// Pure projection and validation helpers for the F-BONUS-001 replan panel.
//
// The browser never solves. These functions only classify the server status,
// summarise the persisted impact and before/after diff, format the churn cost
// and validate the disruption composer. Keeping them pure means the status
// tone, diff summary and form rules are unit-tested without a DOM or a solver.

import type {
  Disruption,
  DisruptionKind,
  ReplanDiff,
  ReplanImpact,
  ReplanRead,
  ReplanRequest,
  SlotPair,
} from "../api/types";

export type ReplanTone = "ok" | "warn" | "danger" | "info" | "idle";

export type ReplanStatusKind = "feasible" | "infeasible" | "unknown" | "unsafe";

export const REPLAN_STATUS_LABEL: Record<ReplanStatusKind, string> = {
  feasible: "FEASIBLE",
  infeasible: "INFEASIBLE",
  unknown: "UNKNOWN",
  unsafe: "UNSAFE",
};

export const PHYSICAL_NIGHT_MIN = 1;
export const PHYSICAL_NIGHT_MAX = 7;
export const MAX_SEED = 2_147_483_647;

// The solver can answer OPTIMAL or FEASIBLE. Both are usable and are shown as
// FEASIBLE. Anything else is either an honest failure or an unrecognised state.
export function classifyReplanStatus(
  status: string | null | undefined,
): ReplanStatusKind {
  switch ((status ?? "").trim().toUpperCase()) {
    case "OPTIMAL":
    case "FEASIBLE":
      return "feasible";
    case "INFEASIBLE":
      return "infeasible";
    case "UNSAFE":
      return "unsafe";
    default:
      return "unknown";
  }
}

export function replanStatusLabel(status: string | null | undefined): string {
  return REPLAN_STATUS_LABEL[classifyReplanStatus(status)];
}

export function replanStatusTone(status: string | null | undefined): ReplanTone {
  switch (classifyReplanStatus(status)) {
    case "feasible":
      return "ok";
    case "infeasible":
    case "unsafe":
      return "danger";
    default:
      return "warn";
  }
}

// A replan is only usable when the server says it is safe and feasible. An
// unsafe or infeasible outcome is never adoptable.
export function isReplanUsable(
  replan: Pick<ReplanRead, "status" | "safe"> | null | undefined,
): boolean {
  if (!replan) return false;
  return replan.safe === true && classifyReplanStatus(replan.status) === "feasible";
}

// A usable replan may still move placements. The "every original placement was
// reused" success copy is only honest when the reused count equals the original
// count, so it can never sit beside a withheld or unsafe outcome.
export function isReplanFullyReused(
  diff: ReplanDiff | null | undefined,
): boolean {
  if (!diff) return false;
  const summary = summariseDiff(diff);
  return summary.reusedAccesses === summary.originalAccesses;
}

// The only condition under which the diff may show the green success message.
export function isReplanSuccess(
  replan: Pick<ReplanRead, "status" | "safe" | "diff"> | null | undefined,
): boolean {
  return isReplanUsable(replan) && isReplanFullyReused(replan?.diff);
}

// ------------------------------------------------------------------ diff

export interface ReplanDiffSummary {
  movedActivities: number;
  movedAccesses: number;
  unchangedActivities: number;
  addedActivities: number;
  removedActivities: number;
  unsatisfiableActivities: number;
  originalAccesses: number;
  replanAccesses: number;
  reusedAccesses: number;
  hasChanges: boolean;
}

export function summariseDiff(
  diff: ReplanDiff | null | undefined,
): ReplanDiffSummary {
  const totals = diff?.totals;
  const moved = diff?.moved?.length ?? 0;
  const added = diff?.added?.length ?? 0;
  const removed = diff?.removed?.length ?? 0;
  const unsatisfiable = diff?.newly_unsatisfiable?.length ?? 0;
  return {
    movedActivities: moved,
    movedAccesses: totals?.moved_accesses ?? 0,
    unchangedActivities: diff?.unchanged?.length ?? 0,
    addedActivities: added,
    removedActivities: removed,
    unsatisfiableActivities: unsatisfiable,
    originalAccesses: totals?.original_accesses ?? 0,
    replanAccesses: totals?.replan_accesses ?? 0,
    reusedAccesses: totals?.reused_accesses ?? 0,
    hasChanges: moved + added + removed + unsatisfiable > 0,
  };
}

export function formatSlot(slot: SlotPair | null | undefined): string {
  if (!slot || typeof slot[0] !== "number") return "—";
  const [week, night] = slot;
  if (night == null) return `W${week}`;
  return `W${week}·N${night}`;
}

export function formatSlotList(slots: SlotPair[] | null | undefined): string {
  if (!slots || slots.length === 0) return "—";
  return slots.map((slot) => formatSlot(slot)).join(", ");
}

export interface ReplanMovedRow {
  activityId: string;
  from: string[];
  to: string[];
}

export function projectMoved(
  diff: ReplanDiff | null | undefined,
): ReplanMovedRow[] {
  return (diff?.moved ?? []).map((entry) => ({
    activityId: entry.activity_id,
    from: (entry.from ?? []).map((slot) => formatSlot(slot)),
    to: (entry.to ?? []).map((slot) => formatSlot(slot)),
  }));
}

// ------------------------------------------------------------------ churn

export function formatChurnCost(churnCost: number | null | undefined): string {
  const moved = Number.isFinite(churnCost) ? Number(churnCost) : 0;
  if (moved <= 0) return "No accesses moved";
  return `${moved} ${moved === 1 ? "access" : "accesses"} moved`;
}

export function churnShare(moved: number, reference: number): string {
  if (!Number.isFinite(reference) || reference <= 0) return "—";
  const safeMoved = Math.max(0, Math.min(moved, reference));
  const percent = Math.round((safeMoved / reference) * 100);
  return `${safeMoved} of ${reference} (${percent}%)`;
}

export function formatChurnSummary(
  churnCost: number | null | undefined,
  referenceAccesses: number | null | undefined,
): string {
  const moved = Number.isFinite(churnCost) ? Number(churnCost) : 0;
  const reference = Number.isFinite(referenceAccesses)
    ? Number(referenceAccesses)
    : 0;
  if (reference <= 0) return formatChurnCost(moved);
  return `${formatChurnCost(moved)} · ${churnShare(moved, reference)}`;
}

// ---------------------------------------------------------------- impact

export interface ReplanImpactSummary {
  invalidPlacements: number;
  affectedActivities: number;
  affectedContracts: number;
  affectedLocationWeeks: number;
  injectedAccessNights: number;
  accessNightsBefore: number;
  accessNightsAfter: number;
}

export function summariseImpact(
  impact: ReplanImpact | null | undefined,
): ReplanImpactSummary {
  return {
    invalidPlacements: impact?.invalid_placements?.length ?? 0,
    affectedActivities: impact?.affected_activities?.length ?? 0,
    affectedContracts: impact?.affected_contracts?.length ?? 0,
    affectedLocationWeeks: impact?.affected_location_weeks?.length ?? 0,
    injectedAccessNights: impact?.workload?.injected_access_nights ?? 0,
    accessNightsBefore: impact?.workload?.access_nights_before ?? 0,
    accessNightsAfter: impact?.workload?.access_nights_after_lower_bound ?? 0,
  };
}

// ------------------------------------------------------- disruption form

export interface DisruptionDraft {
  id: string;
  kind: DisruptionKind;
  locationId: string;
  newSupply: string;
  physicalNight: string;
  weeks: string;
  activityId: string;
  contractNumber: string;
  activityType: string;
  startLocationId: string;
  endLocationId: string;
  totalAccesses: string;
  plannedStartDate: string;
  predecessorActivityId: string;
  activityPriority: string;
}

export function newDisruptionDraft(
  id: string,
  kind: DisruptionKind = "supply_drop",
): DisruptionDraft {
  return {
    id,
    kind,
    locationId: "",
    newSupply: "1",
    physicalNight: "1",
    weeks: "",
    activityId: "",
    contractNumber: "",
    activityType: "",
    startLocationId: "",
    endLocationId: "",
    totalAccesses: "1",
    plannedStartDate: "",
    predecessorActivityId: "",
    activityPriority: "1",
  };
}

export interface WeeksParse {
  weeks: number[] | null;
  error: string | null;
}

// Empty means the whole horizon (null). Otherwise a comma or space separated
// list of 1-based weeks, deduplicated and sorted.
export function parseWeeks(raw: string): WeeksParse {
  const trimmed = raw.trim();
  if (trimmed === "") return { weeks: null, error: null };
  const tokens = trimmed.split(/[\s,]+/).filter(Boolean);
  const weeks = new Set<number>();
  for (const token of tokens) {
    if (!/^\d+$/.test(token)) {
      return { weeks: null, error: `Week "${token}" is not a whole number.` };
    }
    const value = Number(token);
    if (!Number.isInteger(value) || value < 1) {
      return { weeks: null, error: `Week ${token} must be 1 or greater.` };
    }
    weeks.add(value);
  }
  return { weeks: [...weeks].sort((a, b) => a - b), error: null };
}

function parseInteger(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : null;
}

export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return false;
  return date.toISOString().slice(0, 10) === value;
}

export interface DisruptionValidation {
  ok: boolean;
  errors: string[];
  disruption: Disruption | null;
}

export function validateDisruptionDraft(
  draft: DisruptionDraft,
): DisruptionValidation {
  const errors: string[] = [];
  let disruption: Disruption | null = null;

  switch (draft.kind) {
    case "supply_drop": {
      const location = draft.locationId.trim();
      const supply = parseInteger(draft.newSupply);
      if (!location) errors.push("Supply drop needs a location.");
      if (supply === null || supply < 0) {
        errors.push("New supply must be a whole number of 0 or more.");
      }
      if (errors.length === 0 && supply !== null) {
        disruption = {
          kind: "supply_drop",
          location_id: location,
          new_supply: supply,
        };
      }
      break;
    }
    case "location_unavailable": {
      const location = draft.locationId.trim();
      const weeks = parseWeeks(draft.weeks);
      if (!location) errors.push("Location closure needs a location.");
      if (weeks.error) errors.push(weeks.error);
      if (errors.length === 0) {
        disruption = {
          kind: "location_unavailable",
          location_id: location,
          weeks: weeks.weeks,
        };
      }
      break;
    }
    case "night_unavailable": {
      const night = parseInteger(draft.physicalNight);
      const weeks = parseWeeks(draft.weeks);
      if (
        night === null ||
        night < PHYSICAL_NIGHT_MIN ||
        night > PHYSICAL_NIGHT_MAX
      ) {
        errors.push(
          `Physical night must be ${PHYSICAL_NIGHT_MIN} to ${PHYSICAL_NIGHT_MAX}.`,
        );
      }
      if (weeks.error) errors.push(weeks.error);
      if (errors.length === 0 && night !== null) {
        disruption = {
          kind: "night_unavailable",
          physical_night: night,
          weeks: weeks.weeks,
        };
      }
      break;
    }
    case "urgent_activity": {
      const activityId = draft.activityId.trim();
      const contract = draft.contractNumber.trim();
      const start = draft.startLocationId.trim();
      const end = draft.endLocationId.trim();
      const total = parseInteger(draft.totalAccesses);
      const priority = parseInteger(draft.activityPriority);
      const startDate = draft.plannedStartDate.trim();
      if (!activityId) errors.push("Urgent activity needs an activity id.");
      if (!contract) errors.push("Urgent activity needs a contract number.");
      if (!start) errors.push("Urgent activity needs a start location.");
      if (!end) errors.push("Urgent activity needs an end location.");
      if (total === null || total < 1) {
        errors.push("Total accesses must be a whole number of 1 or more.");
      }
      if (priority === null || priority < 1 || priority > 3) {
        errors.push("Activity priority must be 1, 2 or 3.");
      }
      if (!isIsoDate(startDate)) {
        errors.push("Planned start date must be a valid date (YYYY-MM-DD).");
      }
      if (errors.length === 0 && total !== null && priority !== null) {
        disruption = {
          kind: "urgent_activity",
          activity_id: activityId,
          contract_number: contract,
          activity_type: draft.activityType.trim() || null,
          start_location_id: start,
          end_location_id: end,
          total_accesses: total,
          planned_start_date: startDate,
          predecessor_activity_id: draft.predecessorActivityId.trim() || null,
          activity_priority: priority,
        };
      }
      break;
    }
  }

  return { ok: disruption !== null, errors, disruption };
}

export interface ReplanDraftValidation {
  ok: boolean;
  errors: string[];
  disruptions: Disruption[];
}

export function validateReplanDrafts(
  drafts: DisruptionDraft[],
): ReplanDraftValidation {
  if (drafts.length === 0) {
    return {
      ok: false,
      errors: ["Add at least one disruption before submitting."],
      disruptions: [],
    };
  }
  const errors: string[] = [];
  const disruptions: Disruption[] = [];
  drafts.forEach((draft, index) => {
    const result = validateDisruptionDraft(draft);
    if (!result.ok || !result.disruption) {
      errors.push(`Disruption ${index + 1}: ${result.errors.join(" ")}`);
      return;
    }
    disruptions.push(result.disruption);
  });
  return { ok: errors.length === 0, errors, disruptions };
}

export interface ReplanOptionsDraft {
  timeLimitSeconds: string;
  seed: string;
  horizonExtensionWeeks: string;
}

export function newReplanOptions(): ReplanOptionsDraft {
  return { timeLimitSeconds: "", seed: "", horizonExtensionWeeks: "" };
}

export interface ReplanRequestBuild {
  ok: boolean;
  errors: string[];
  payload: ReplanRequest | null;
}

export function buildReplanRequest(
  drafts: DisruptionDraft[],
  options: ReplanOptionsDraft,
): ReplanRequestBuild {
  const validation = validateReplanDrafts(drafts);
  const errors = [...validation.errors];
  const payload: ReplanRequest = { disruptions: validation.disruptions };

  const timeLimit = options.timeLimitSeconds.trim();
  if (timeLimit !== "") {
    const value = parseInteger(timeLimit);
    if (value === null || value <= 0) {
      errors.push("Time limit must be a positive whole number of seconds.");
    } else {
      payload.time_limit_seconds = value;
    }
  }

  const seed = options.seed.trim();
  if (seed !== "") {
    const value = parseInteger(seed);
    if (value === null || value < 0 || value > MAX_SEED) {
      errors.push(`Seed must be an integer from 0 to ${MAX_SEED}.`);
    } else {
      payload.seed = value;
    }
  }

  const horizon = options.horizonExtensionWeeks.trim();
  if (horizon !== "") {
    const value = parseInteger(horizon);
    if (value === null || value < 0) {
      errors.push("Horizon extension must be a whole number of 0 or more weeks.");
    } else {
      payload.horizon_extension_weeks = value;
    }
  }

  const ok = errors.length === 0 && validation.disruptions.length > 0;
  return { ok, errors, payload: ok ? payload : null };
}

function describeWeeks(weeks: number[] | null): string {
  return weeks && weeks.length > 0 ? ` weeks ${weeks.join(", ")}` : " all weeks";
}

export function describeDisruption(disruption: Disruption): string {
  switch (disruption.kind) {
    case "supply_drop":
      return `Supply drop ${disruption.location_id} → ${disruption.new_supply}`;
    case "location_unavailable":
      return `Close ${disruption.location_id}${describeWeeks(disruption.weeks)}`;
    case "night_unavailable":
      return `Close night ${disruption.physical_night}${describeWeeks(
        disruption.weeks,
      )}`;
    case "urgent_activity":
      return `Inject ${disruption.activity_id} (${disruption.contract_number}) ×${disruption.total_accesses}`;
  }
}

export const DISRUPTION_KIND_LABEL: Record<DisruptionKind, string> = {
  supply_drop: "Supply drop",
  location_unavailable: "Location unavailable",
  night_unavailable: "Night unavailable",
  urgent_activity: "Urgent activity injection",
};
