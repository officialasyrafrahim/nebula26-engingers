// Pure projection and validation helpers for the F-BONUS-002 what-if sandbox.
//
// The browser never solves. These functions classify the server status, project
// the baseline/variant metric delta, read the fragility signal, describe the
// applied knobs and validate the knob composer. Keeping them pure means the
// status tone, metric projection and form rules are unit-tested without a DOM
// or a solver.

import type {
  SandboxFragility,
  SandboxMetricSet,
  SandboxOutcomeRead,
  SandboxRead,
  SandboxRequest,
  Scenario,
} from "../api/types";

// Local copies of the shared formatters. Keeping them here means this module has
// no runtime import, so the pure projection can run under the Node test runner
// without a bundler.
function formatInt(value: number): string {
  return value.toLocaleString();
}

function formatDecimal(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

export type SandboxTone = "ok" | "warn" | "danger" | "info" | "idle";

export type SandboxStatusKind = "feasible" | "infeasible" | "unsafe" | "unknown";

export const SANDBOX_STATUS_LABEL: Record<SandboxStatusKind, string> = {
  feasible: "FEASIBLE",
  infeasible: "INFEASIBLE",
  unsafe: "UNSAFE",
  unknown: "UNKNOWN",
};

export const MAX_SANDBOX_SEED = 2_147_483_647;
export const MIN_FRAGILITY_TRIALS = 2;
export const MAX_FRAGILITY_TRIALS = 64;
export const DEFAULT_FRAGILITY_TRIALS = 16;

// The solver reports OPTIMAL or FEASIBLE; both are usable and shown as
// FEASIBLE. Anything the engine does not prove is either an honest failure or an
// unrecognised state.
export function classifySandboxStatus(
  status: string | null | undefined,
): SandboxStatusKind {
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

export function sandboxStatusLabel(status: string | null | undefined): string {
  return SANDBOX_STATUS_LABEL[classifySandboxStatus(status)];
}

export function sandboxStatusTone(status: string | null | undefined): SandboxTone {
  switch (classifySandboxStatus(status)) {
    case "feasible":
      return "ok";
    case "infeasible":
    case "unsafe":
      return "danger";
    default:
      return "warn";
  }
}

// A variant is only usable when the server proved it feasible and the
// independent physical witness accepted it.
export function isSandboxVariantUsable(
  outcome:
    | Pick<SandboxOutcomeRead, "feasible" | "safe" | "status">
    | null
    | undefined,
): boolean {
  if (!outcome) return false;
  return (
    outcome.safe === true &&
    outcome.feasible === true &&
    classifySandboxStatus(outcome.status) === "feasible"
  );
}

// ------------------------------------------------------------------ metrics

export type SandboxMetricDirection = "lower" | "higher" | "neutral";

export interface SandboxMetricField {
  key: keyof SandboxMetricSet;
  label: string;
  hint: string;
  direction: SandboxMetricDirection;
  kind: "int" | "score";
}

// Objective facts in the order the board presents them. Overrun, excess access
// and ECLO are penalties, so a fall is an improvement. Access nights are a
// neutral count and the objective score is minimised.
export const SANDBOX_METRIC_FIELDS: SandboxMetricField[] = [
  {
    key: "overrun_days_total",
    label: "Overrun days",
    hint: "Sum of contract overrun days.",
    direction: "lower",
    kind: "int",
  },
  {
    key: "excess_access_nights_total",
    label: "Excess access nights",
    hint: "Access nights beyond the plan.",
    direction: "lower",
    kind: "int",
  },
  {
    key: "eclo_nights_total",
    label: "ECLO nights",
    hint: "Nights using an early close allowance.",
    direction: "lower",
    kind: "int",
  },
  {
    key: "access_nights_total",
    label: "Access nights",
    hint: "Total scheduled access nights.",
    direction: "neutral",
    kind: "int",
  },
  {
    key: "score",
    label: "Objective score",
    hint: "Server objective value, minimised.",
    direction: "lower",
    kind: "score",
  },
];

export interface SandboxMetricProjection {
  key: string;
  label: string;
  hint: string;
  baseline: number;
  variant: number;
  delta: number;
  baselineText: string;
  variantText: string;
  deltaText: string;
  tone: SandboxTone;
}

export function formatMetricValue(
  value: number | null | undefined,
  kind: "int" | "score",
): string {
  if (value == null || Number.isNaN(value)) return "—";
  return kind === "score" ? formatDecimal(value) : formatInt(value);
}

export function formatMetricDelta(
  delta: number | null | undefined,
  kind: "int" | "score",
): string {
  if (delta == null || Number.isNaN(delta) || delta === 0) return "0";
  const magnitude =
    kind === "score" ? formatDecimal(Math.abs(delta)) : formatInt(Math.abs(delta));
  return `${delta > 0 ? "+" : "-"}${magnitude}`;
}

export function metricTone(
  delta: number,
  direction: SandboxMetricDirection,
): SandboxTone {
  if (delta === 0 || direction === "neutral") return "idle";
  const improved = direction === "lower" ? delta < 0 : delta > 0;
  return improved ? "ok" : "warn";
}

export function projectSandboxMetrics(
  read: Pick<SandboxRead, "baseline" | "variant" | "delta">,
): SandboxMetricProjection[] {
  return SANDBOX_METRIC_FIELDS.map((field) => {
    const baseline = Number(read.baseline?.[field.key] ?? 0);
    const variant = Number(read.variant.metrics?.[field.key] ?? 0);
    const delta = Number(read.delta?.[field.key] ?? variant - baseline);
    return {
      key: field.key,
      label: field.label,
      hint: field.hint,
      baseline,
      variant,
      delta,
      baselineText: formatMetricValue(baseline, field.kind),
      variantText: formatMetricValue(variant, field.kind),
      deltaText: formatMetricDelta(delta, field.kind),
      tone: metricTone(delta, field.direction),
    };
  });
}

// ----------------------------------------------------------------- fragility

export interface FragilityReading {
  present: boolean;
  tone: SandboxTone;
  headline: string;
  detail: string;
  breakingSupply: number | null;
  smallestReduction: number | null;
  trials: number;
  bounded: boolean;
}

export function fragilityReading(
  fragility: SandboxFragility | null | undefined,
): FragilityReading {
  if (!fragility) {
    return {
      present: false,
      tone: "idle",
      headline: "No fragility signal requested",
      detail:
        "Choose a fragility location to probe the smallest supply reduction that breaks feasibility.",
      breakingSupply: null,
      smallestReduction: null,
      trials: 0,
      bounded: true,
    };
  }

  const {
    location_id,
    base_supply,
    feasible_floor,
    breaking_new_supply,
    smallest_supply_reduction,
    trials,
    bounded,
    note,
  } = fragility;

  const shared = {
    present: true,
    breakingSupply: breaking_new_supply,
    smallestReduction: smallest_supply_reduction,
    trials,
    bounded,
  };

  if (smallest_supply_reduction != null) {
    const tone: SandboxTone =
      smallest_supply_reduction <= 1
        ? "danger"
        : smallest_supply_reduction <= 3
          ? "warn"
          : "ok";
    return {
      ...shared,
      tone,
      headline: `${location_id} breaks at supply ${breaking_new_supply}`,
      detail: `Supply ${base_supply} is feasible at a floor of ${feasible_floor}. The smallest breaking reduction is ${smallest_supply_reduction}.`,
    };
  }

  if (base_supply === 0) {
    return {
      ...shared,
      tone: "idle",
      headline: `${location_id} already has zero supply`,
      detail: note,
    };
  }

  if (feasible_floor === 0) {
    return {
      ...shared,
      tone: "ok",
      headline: `${location_id} stays feasible even at supply 0`,
      detail: note,
    };
  }

  return {
    ...shared,
    tone: "info",
    headline: `No breaking supply found for ${location_id}`,
    detail: note,
  };
}

// -------------------------------------------------------------------- knobs

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function describeOverrides(value: unknown): string[] {
  if (!isRecord(value)) return [];
  return Object.entries(value)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => `${key} → ${String(item)}`);
}

// Human description of the knobs the server actually applied, never the knobs
// the planner merely typed.
export function describeApplied(applied: Record<string, unknown>): string[] {
  const parts: string[] = [];
  if (typeof applied.scenario === "string") {
    parts.push(`scenario ${applied.scenario}`);
  }

  const supply = describeOverrides(applied.supply);
  if (supply.length > 0) parts.push(`supply ${supply.join(", ")}`);

  const workfronts = describeOverrides(applied.workfronts);
  if (workfronts.length > 0) parts.push(`workfronts ${workfronts.join(", ")}`);

  if (typeof applied.horizon_extension_weeks === "number") {
    const weeks = applied.horizon_extension_weeks;
    parts.push(`horizon +${weeks} ${weeks === 1 ? "week" : "weeks"}`);
  }
  if (typeof applied.eclo_allowed === "boolean") {
    parts.push(`ECLO ${applied.eclo_allowed ? "allowed" : "disallowed"}`);
  }
  return parts;
}

// --------------------------------------------------------------- composer

export interface SandboxDraft {
  scenario: "" | Scenario;
  supplyLocationId: string;
  supplyValue: string;
  workfrontContract: string;
  workfrontValue: string;
  horizonExtensionWeeks: string;
  ecloAllowed: "inherit" | "true" | "false";
  fragilityLocationId: string;
  timeLimitSeconds: string;
  seed: string;
  fragilityMaxTrials: string;
}

export function newSandboxDraft(): SandboxDraft {
  return {
    scenario: "",
    supplyLocationId: "",
    supplyValue: "",
    workfrontContract: "",
    workfrontValue: "",
    horizonExtensionWeeks: "",
    ecloAllowed: "inherit",
    fragilityLocationId: "",
    timeLimitSeconds: "",
    seed: "",
    fragilityMaxTrials: String(DEFAULT_FRAGILITY_TRIALS),
  };
}

function parseInteger(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : null;
}

export interface SandboxRequestBuild {
  ok: boolean;
  errors: string[];
  payload: SandboxRequest | null;
}

export function buildSandboxRequest(draft: SandboxDraft): SandboxRequestBuild {
  const errors: string[] = [];
  const payload: SandboxRequest = {};
  let knobs = 0;

  if (draft.scenario !== "") {
    payload.scenario = draft.scenario;
    knobs += 1;
  }

  const supplyLocation = draft.supplyLocationId.trim();
  const supplyRaw = draft.supplyValue.trim();
  if (supplyLocation !== "" || supplyRaw !== "") {
    if (supplyLocation === "") {
      errors.push("Choose a location for the supply override.");
    }
    const supply = parseInteger(supplyRaw);
    if (supply === null || supply < 0) {
      errors.push("Supply override must be a whole number of 0 or more.");
    } else if (supplyLocation !== "") {
      payload.supply = { [supplyLocation]: supply };
      knobs += 1;
    }
  }

  const workfrontContract = draft.workfrontContract.trim();
  const workfrontRaw = draft.workfrontValue.trim();
  if (workfrontContract !== "" || workfrontRaw !== "") {
    if (workfrontContract === "") {
      errors.push("Choose a contract for the workfront override.");
    }
    const workfront = parseInteger(workfrontRaw);
    if (workfront === null || workfront < 1) {
      errors.push("Workfront override must be a whole number of 1 or more.");
    } else if (workfrontContract !== "") {
      payload.workfronts = { [workfrontContract]: workfront };
      knobs += 1;
    }
  }

  const horizonRaw = draft.horizonExtensionWeeks.trim();
  if (horizonRaw !== "") {
    const horizon = parseInteger(horizonRaw);
    if (horizon === null || horizon < 0) {
      errors.push("Horizon extension must be a whole number of 0 or more weeks.");
    } else {
      payload.horizon_extension_weeks = horizon;
      knobs += 1;
    }
  }

  if (draft.ecloAllowed !== "inherit") {
    payload.eclo_allowed = draft.ecloAllowed === "true";
    knobs += 1;
  }

  const fragilityLocation = draft.fragilityLocationId.trim();
  if (fragilityLocation !== "") {
    payload.fragility_location_id = fragilityLocation;
    knobs += 1;
  }

  const timeLimitRaw = draft.timeLimitSeconds.trim();
  if (timeLimitRaw !== "") {
    const timeLimit = parseInteger(timeLimitRaw);
    if (timeLimit === null || timeLimit <= 0) {
      errors.push("Time limit must be a positive whole number of seconds.");
    } else {
      payload.time_limit_seconds = timeLimit;
    }
  }

  const seedRaw = draft.seed.trim();
  if (seedRaw !== "") {
    const seed = parseInteger(seedRaw);
    if (seed === null || seed < 0 || seed > MAX_SANDBOX_SEED) {
      errors.push(`Seed must be an integer from 0 to ${MAX_SANDBOX_SEED}.`);
    } else {
      payload.seed = seed;
    }
  }

  const trialsRaw = draft.fragilityMaxTrials.trim();
  if (trialsRaw !== "") {
    const trials = parseInteger(trialsRaw);
    if (
      trials === null ||
      trials < MIN_FRAGILITY_TRIALS ||
      trials > MAX_FRAGILITY_TRIALS
    ) {
      errors.push(
        `Fragility trials must be a whole number from ${MIN_FRAGILITY_TRIALS} to ${MAX_FRAGILITY_TRIALS}.`,
      );
    } else {
      payload.fragility_max_trials = trials;
    }
  }

  if (knobs === 0) {
    errors.push(
      "Choose at least one knob or a fragility location before running the what-if.",
    );
  }

  const ok = errors.length === 0;
  return { ok, errors, payload: ok ? payload : null };
}

export const SANDBOX_SCENARIOS: Scenario[] = ["A", "B", "C"];
