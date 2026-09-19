// Pure validation and projection helpers for the F-BONUS-003 schedule query.
//
// The grammar is closed and mirrors backend/app/modules/explain/query.py. The
// browser only pre-checks the shape so an unsupported query is shown as
// rejected; the server stays the authority and answers from persisted evidence
// only. Nothing here reaches the network.

import type {
  QueryKind,
  ScheduleQueryCitation,
  ScheduleQueryResponse,
} from "../api/types";

export type QueryTone = "ok" | "warn" | "danger" | "info" | "idle";

export const MAX_QUERY_LENGTH = 200;
const TOKEN = "[A-Za-z0-9_.:-]+";

export const QUERY_GRAMMAR_HELP =
  "Supported queries: why <activity_id>, downstream <activity_id>, " +
  "capacity <location_id> week <n>, milestone <contract_number>.";

const WHY_RE = new RegExp(`^why\\s+(${TOKEN})$`, "i");
const DOWNSTREAM_RE = new RegExp(`^downstream\\s+(${TOKEN})$`, "i");
const CAPACITY_RE = new RegExp(
  `^(?:capacity|co-?share)\\s+(${TOKEN})\\s+week\\s+(\\d+)$`,
  "i",
);
const MILESTONE_RE = new RegExp(`^(?:milestone|handover)\\s+(${TOKEN})$`, "i");

export interface ParsedLocalQuery {
  ok: boolean;
  kind: QueryKind | null;
  normalized: string;
  id: string | null;
  week: number | null;
  error: string | null;
}

export function normalizeQuery(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

export function parseLocalQuery(text: string): ParsedLocalQuery {
  const normalized = normalizeQuery(text);
  const base = {
    ok: false,
    kind: null,
    normalized,
    id: null,
    week: null,
  } as const;

  if (normalized === "") {
    return { ...base, error: `Empty query. ${QUERY_GRAMMAR_HELP}` };
  }
  if (normalized.length > MAX_QUERY_LENGTH) {
    return {
      ...base,
      error: `Query exceeds ${MAX_QUERY_LENGTH} characters.`,
    };
  }

  const why = WHY_RE.exec(normalized);
  if (why) {
    return {
      ok: true,
      kind: "why_moved",
      normalized,
      id: why[1],
      week: null,
      error: null,
    };
  }

  const downstream = DOWNSTREAM_RE.exec(normalized);
  if (downstream) {
    return {
      ok: true,
      kind: "downstream_risk",
      normalized,
      id: downstream[1],
      week: null,
      error: null,
    };
  }

  const capacity = CAPACITY_RE.exec(normalized);
  if (capacity) {
    const week = Number(capacity[2]);
    if (!Number.isInteger(week) || week < 1) {
      return {
        ...base,
        kind: "capacity_check",
        id: capacity[1],
        error: "Week must be a positive integer.",
      };
    }
    return {
      ok: true,
      kind: "capacity_check",
      normalized,
      id: capacity[1],
      week,
      error: null,
    };
  }

  const milestone = MILESTONE_RE.exec(normalized);
  if (milestone) {
    return {
      ok: true,
      kind: "milestone_brief",
      normalized,
      id: milestone[1],
      week: null,
      error: null,
    };
  }

  return { ...base, error: `Unsupported query shape. ${QUERY_GRAMMAR_HELP}` };
}

// ------------------------------------------------------------------ outcome

export type QueryOutcome =
  | "idle"
  | "answerable"
  | "unanswerable"
  | "rejected"
  | "error";

export const QUERY_OUTCOME_LABEL: Record<QueryOutcome, string> = {
  idle: "No query",
  answerable: "Answered",
  unanswerable: "Unanswerable",
  rejected: "Rejected",
  error: "Failed",
};

export function queryOutcomeTone(outcome: QueryOutcome): QueryTone {
  switch (outcome) {
    case "answerable":
      return "ok";
    case "unanswerable":
      return "warn";
    case "rejected":
    case "error":
      return "danger";
    default:
      return "idle";
  }
}

export function queryOutcomeLabel(outcome: QueryOutcome): string {
  return QUERY_OUTCOME_LABEL[outcome];
}

// ---------------------------------------------------------------- projection

export function formatEvidenceValue(value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return value.map((item) => formatEvidenceValue(item)).join(", ");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "—";
    return JSON.stringify(value);
  }
  return String(value);
}

export interface EvidenceField {
  key: string;
  value: string;
}

export function projectEvidence(evidence: Record<string, unknown>): EvidenceField[] {
  return Object.entries(evidence ?? {})
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => ({ key, value: formatEvidenceValue(value) }));
}

export interface CitationProjection {
  source: string;
  fields: EvidenceField[];
}

export function projectCitations(
  citations: ScheduleQueryCitation[],
): CitationProjection[] {
  return (citations ?? []).map((citation) => ({
    source: citation.source,
    fields: projectEvidence(citation.fields ?? {}),
  }));
}

// --------------------------------------------------------------- vocabulary

export interface QueryVocabulary {
  activities: string[];
  contracts: string[];
  locations: string[];
  weeks: number[];
}

export interface QueryExample {
  label: string;
  query: string;
}

// Deterministic, concrete examples drawn from the loaded network so the planner
// can see the exact grammar shape. Falls back to placeholders when the run has
// no usable vocabulary.
export function buildQueryExamples(vocabulary: QueryVocabulary): QueryExample[] {
  const activity = vocabulary.activities[0] ?? "A1";
  const contract = vocabulary.contracts[0] ?? "C1";
  const location = vocabulary.locations[0] ?? "LOC1";
  const week = vocabulary.weeks[0] ?? 1;
  return [
    { label: "Why an activity moved", query: `why ${activity}` },
    { label: "Downstream delay risk", query: `downstream ${activity}` },
    { label: "Location-week capacity", query: `capacity ${location} week ${week}` },
    { label: "Contract milestone", query: `milestone ${contract}` },
  ];
}

// A convenience read used by the panel to decide the result tone without
// duplicating the answerable/rejected distinction.
export function classifyQueryResponse(
  response: Pick<ScheduleQueryResponse, "answerable"> | null | undefined,
  rejected: boolean,
  failed: boolean,
): QueryOutcome {
  if (failed) return "error";
  if (rejected) return "rejected";
  if (!response) return "idle";
  return response.answerable ? "answerable" : "unanswerable";
}
