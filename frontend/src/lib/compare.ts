// Pure side-by-side projection of the three scenario results for one run.
// Every number is read from the persisted validator report (soft_scores and
// detail). The capacity policy copy comes from the published scenario specs.
// Nothing is recomputed or filled in: an absent scenario simply has no row.
//
// A, B and C optimise different objective formulas, so the projection never
// ranks them. This module exposes no "best" or "leader" value and carries a
// standing caveat that the numbers are not directly comparable.

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

// The three scenarios are not a leaderboard. This copy is rendered beside the
// table and is intentionally persistent for the life of the comparison.
export const SCENARIO_COMPARISON_CAVEAT =
  "Scenarios A, B and C optimise different objective formulas. Their numbers are not directly comparable and must not be ranked or read as a leaderboard. Read each scenario only against its own formula.";

export interface ScenarioTradeoff {
  scenario: Scenario;
  title: string;
  objective: string;
  note: string;
}

export interface ScenarioComparisonCaveat {
  rankable: false;
  message: string;
  tradeoffs: ScenarioTradeoff[];
}

export function buildComparisonCaveat(
  rows: ScenarioCompareRow[],
): ScenarioComparisonCaveat {
  return {
    rankable: false,
    message: SCENARIO_COMPARISON_CAVEAT,
    tradeoffs: rows.map((row) => ({
      scenario: row.scenario,
      title: row.spec.title,
      objective: row.spec.objective,
      note: `${row.spec.title} is tuned for its own formula. Read its figures as a trade-off within that formula, never as a rank against the other scenarios.`,
    })),
  };
}

export interface ScenarioCompareResult {
  rows: ScenarioCompareRow[];
  missing: Scenario[];
  canCompare: boolean;
  caveat: ScenarioComparisonCaveat;
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
    caveat: buildComparisonCaveat(rows),
  };
}
