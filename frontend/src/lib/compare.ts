// Pure side-by-side projection of the three scenario results for one run.
// Every number is read from the persisted validator report (soft_scores and
// detail). The capacity policy copy comes from the published scenario specs.
// Nothing is recomputed or filled in: an absent scenario simply has no row.

import type { Scenario, ValidatorReport } from "../api/types";
import { scenarioSpec, type ScenarioSpec } from "./scenarios.ts";

export interface ScenarioCompareEntry {
  scenario: Scenario;
  jobId: string;
  report: ValidatorReport;
}

export interface ScenarioCompareRow {
  scenario: Scenario;
  spec: ScenarioSpec;
  jobId: string;
  feasible: boolean;
  readyForSubmission: boolean;
  authority: string;
  priorityWeightedOverrun: number;
  overrunDaysTotal: number;
  contractsOverrunning: number;
  excessAccessNights: number;
  ecloNights: number;
  capacityHotspots: number;
  capacityExcess: number;
  nightsScheduled: number;
  priorityOverrun: Record<string, number>;
}

export type CompareMetric =
  | "priorityWeightedOverrun"
  | "excessAccessNights"
  | "ecloNights"
  | "capacityExcess";

export interface ScenarioCompareResult {
  rows: ScenarioCompareRow[];
  missing: Scenario[];
  canCompare: boolean;
  // Lowest value per lower-is-better metric. Ties keep every scenario, and a
  // metric with no evidence stays empty.
  leaders: Record<CompareMetric, Scenario[]>;
}

const SCENARIO_ORDER: Scenario[] = ["A", "B", "C"];

function toRow(entry: ScenarioCompareEntry): ScenarioCompareRow {
  const soft = entry.report.soft_scores;
  const detail = entry.report.detail;
  const hotspots = detail.capacity_hotspots ?? [];
  return {
    scenario: entry.scenario,
    spec: scenarioSpec(entry.scenario),
    jobId: entry.jobId,
    feasible: entry.report.feasible,
    readyForSubmission: entry.report.ready_for_submission,
    authority: entry.report.authority,
    priorityWeightedOverrun: soft.priority_weighted_score,
    overrunDaysTotal: soft.overrun_days_total,
    contractsOverrunning: soft.contracts_overrunning,
    excessAccessNights: soft.excess_access_nights_total,
    ecloNights: soft.eclo_nights_total,
    capacityHotspots: hotspots.length,
    capacityExcess: hotspots.reduce((sum, spot) => sum + spot.excess, 0),
    nightsScheduled: detail.nights_scheduled,
    priorityOverrun: soft.priority_overrun ?? {},
  };
}

function leadersFor(
  rows: ScenarioCompareRow[],
  metric: CompareMetric,
): Scenario[] {
  if (rows.length === 0) return [];
  const values = rows.map((row) => row[metric]);
  if (values.every((value) => !Number.isFinite(value))) return [];
  const lowest = Math.min(...values.filter((value) => Number.isFinite(value)));
  return rows
    .filter((row) => Number.isFinite(row[metric]) && row[metric] === lowest)
    .map((row) => row.scenario);
}

export function buildScenarioComparison(
  entries: ScenarioCompareEntry[],
): ScenarioCompareResult {
  const byScenario = new Map<Scenario, ScenarioCompareEntry>();
  for (const entry of entries) {
    if (!entry.report) continue;
    byScenario.set(entry.scenario, entry);
  }

  const rows = SCENARIO_ORDER.filter((scenario) => byScenario.has(scenario)).map(
    (scenario) => toRow(byScenario.get(scenario)!),
  );
  const missing = SCENARIO_ORDER.filter((scenario) => !byScenario.has(scenario));

  return {
    rows,
    missing,
    canCompare: rows.length >= 2,
    leaders: {
      priorityWeightedOverrun: leadersFor(rows, "priorityWeightedOverrun"),
      excessAccessNights: leadersFor(rows, "excessAccessNights"),
      ecloNights: leadersFor(rows, "ecloNights"),
      capacityExcess: leadersFor(rows, "capacityExcess"),
    },
  };
}
