import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { Scenario, ValidatorReport } from "../src/api/types.ts";
import {
  buildScenarioComparison,
  type ScenarioCompareEntry,
} from "../src/lib/compare.ts";

function report(
  scenario: Scenario,
  overrides: {
    priorityWeightedScore: number;
    excess: number;
    eclo: number;
    capacityExcess?: number;
    nightsScheduled?: number;
    feasible?: boolean;
    ready?: boolean;
  },
): ValidatorReport {
  return {
    scenario,
    feasible: overrides.feasible ?? true,
    workload_complete: true,
    ready_for_submission: overrides.ready ?? true,
    authority: "official",
    validator_source: "official",
    hard_violations: [],
    soft_scores: {
      scenario,
      overrun_days_total: 10,
      contracts_overrunning: 1,
      earliness_days_total: 0,
      excess_access_nights_total: overrides.excess,
      eclo_nights_total: overrides.eclo,
      priority_overrun: { "1": 4, "2": 2, "3": 1 },
      priority_weighted_score: overrides.priorityWeightedScore,
      objective_score: overrides.priorityWeightedScore,
      formula_version: "v1",
    },
    detail: {
      capacity_hotspots:
        overrides.capacityExcess && overrides.capacityExcess > 0
          ? [
              {
                location_id: "PLAT:ALP:S01:EB",
                week: 1,
                used: 2,
                capacity: 1,
                excess: overrides.capacityExcess,
              },
            ]
          : [],
      nights_scheduled: overrides.nightsScheduled ?? 5,
      eclo_nights: overrides.eclo,
    },
    parse_errors: [],
  };
}

function entry(
  scenario: Scenario,
  value: Parameters<typeof report>[1],
): ScenarioCompareEntry {
  return { scenario, jobId: `job-${scenario}`, report: report(scenario, value) };
}

describe("buildScenarioComparison", () => {
  it("requires at least two scenarios and names the missing ones", () => {
    const onlyA = buildScenarioComparison([
      entry("A", { priorityWeightedScore: 5, excess: 1, eclo: 0 }),
    ]);
    assert.equal(onlyA.canCompare, false);
    assert.deepEqual(onlyA.missing, ["B", "C"]);
    assert.deepEqual(
      onlyA.rows.map((row) => row.scenario),
      ["A"],
    );
  });

  it("orders rows A, B, C and derives the capacity detail", () => {
    const result = buildScenarioComparison([
      entry("C", { priorityWeightedScore: 30, excess: 2, eclo: 1, capacityExcess: 1 }),
      entry("A", { priorityWeightedScore: 10, excess: 0, eclo: 0 }),
      entry("B", { priorityWeightedScore: 20, excess: 3, eclo: 4, capacityExcess: 0 }),
    ]);
    assert.equal(result.canCompare, true);
    assert.deepEqual(
      result.rows.map((row) => row.scenario),
      ["A", "B", "C"],
    );
    assert.deepEqual(result.missing, []);
    const c = result.rows.find((row) => row.scenario === "C")!;
    assert.equal(c.capacityHotspots, 1);
    assert.equal(c.capacityExcess, 1);
    assert.equal(c.spec.id, "C");
  });

  it("marks the lowest value per lower-is-better metric", () => {
    const result = buildScenarioComparison([
      entry("A", { priorityWeightedScore: 10, excess: 5, eclo: 0 }),
      entry("B", { priorityWeightedScore: 20, excess: 1, eclo: 8 }),
      entry("C", { priorityWeightedScore: 15, excess: 3, eclo: 2 }),
    ]);
    assert.deepEqual(result.leaders.priorityWeightedOverrun, ["A"]);
    assert.deepEqual(result.leaders.excessAccessNights, ["B"]);
    assert.deepEqual(result.leaders.ecloNights, ["A"]);
  });

  it("keeps every scenario on a tie", () => {
    const result = buildScenarioComparison([
      entry("A", { priorityWeightedScore: 10, excess: 2, eclo: 1 }),
      entry("B", { priorityWeightedScore: 10, excess: 2, eclo: 1 }),
    ]);
    assert.deepEqual(result.leaders.priorityWeightedOverrun, ["A", "B"]);
    assert.deepEqual(result.leaders.excessAccessNights, ["A", "B"]);
    assert.deepEqual(result.leaders.ecloNights, ["A", "B"]);
  });
});
