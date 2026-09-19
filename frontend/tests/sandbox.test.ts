import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildSandboxRequest,
  classifySandboxStatus,
  DEFAULT_FRAGILITY_TRIALS,
  describeApplied,
  formatMetricDelta,
  formatMetricValue,
  fragilityReading,
  isSandboxVariantUsable,
  metricTone,
  newSandboxDraft,
  projectSandboxMetrics,
  sandboxStatusLabel,
  sandboxStatusTone,
} from "../src/lib/sandbox.ts";

function read(baseline: Record<string, number>, variant: Record<string, number>) {
  const delta: Record<string, number> = {};
  for (const key of Object.keys(baseline)) {
    delta[key] = (variant[key] ?? 0) - (baseline[key] ?? 0);
  }
  return {
    baseline,
    variant: { metrics: variant },
    delta,
  };
}

describe("classifySandboxStatus", () => {
  it("maps the solver's proven statuses to feasible", () => {
    assert.equal(classifySandboxStatus("OPTIMAL"), "feasible");
    assert.equal(classifySandboxStatus("feasible"), "feasible");
    assert.equal(classifySandboxStatus(" FEASIBLE "), "feasible");
  });

  it("maps failures and unknown statuses honestly", () => {
    assert.equal(classifySandboxStatus("INFEASIBLE"), "infeasible");
    assert.equal(classifySandboxStatus("UNSAFE"), "unsafe");
    assert.equal(classifySandboxStatus("TIMED_OUT"), "unknown");
    assert.equal(classifySandboxStatus(""), "unknown");
    assert.equal(classifySandboxStatus(null), "unknown");
  });

  it("labels and tones the four states", () => {
    assert.equal(sandboxStatusLabel("OPTIMAL"), "FEASIBLE");
    assert.equal(sandboxStatusLabel("INFEASIBLE"), "INFEASIBLE");
    assert.equal(sandboxStatusTone("OPTIMAL"), "ok");
    assert.equal(sandboxStatusTone("INFEASIBLE"), "danger");
    assert.equal(sandboxStatusTone("UNSAFE"), "danger");
    assert.equal(sandboxStatusTone("TIMED_OUT"), "warn");
  });
});

describe("isSandboxVariantUsable", () => {
  it("requires both safety and a proven feasible status", () => {
    assert.equal(
      isSandboxVariantUsable({ feasible: true, safe: true, status: "OPTIMAL" }),
      true,
    );
    assert.equal(
      isSandboxVariantUsable({ feasible: true, safe: false, status: "OPTIMAL" }),
      false,
    );
    assert.equal(
      isSandboxVariantUsable({ feasible: false, safe: false, status: "UNSAFE" }),
      false,
    );
    assert.equal(isSandboxVariantUsable(null), false);
  });
});

describe("metric tone and formatting", () => {
  it("treats a fall as an improvement when lower is better", () => {
    assert.equal(metricTone(-2, "lower"), "ok");
    assert.equal(metricTone(2, "lower"), "warn");
    assert.equal(metricTone(0, "lower"), "idle");
  });

  it("never judges a neutral metric", () => {
    assert.equal(metricTone(-5, "neutral"), "idle");
    assert.equal(metricTone(5, "neutral"), "idle");
  });

  it("formats integers and scores", () => {
    assert.equal(formatMetricValue(1234, "int"), (1234).toLocaleString());
    assert.equal(formatMetricValue(0.5, "score"), "0.50");
    assert.equal(formatMetricValue(3, "score"), "3");
    assert.equal(formatMetricValue(null, "int"), "—");
  });

  it("formats signed deltas", () => {
    assert.equal(formatMetricDelta(0, "int"), "0");
    assert.equal(formatMetricDelta(4, "int"), "+4");
    assert.equal(formatMetricDelta(-4, "int"), "-4");
    assert.equal(formatMetricDelta(0.25, "score"), "+0.25");
    assert.equal(formatMetricDelta(-0.5, "score"), "-0.50");
  });
});

describe("projectSandboxMetrics", () => {
  it("keeps the declared field order and marks neutral counts", () => {
    const rows = projectSandboxMetrics(
      read(
        {
          overrun_days_total: 10,
          excess_access_nights_total: 4,
          eclo_nights_total: 2,
          access_nights_total: 40,
          score: 12.5,
        },
        {
          overrun_days_total: 8,
          excess_access_nights_total: 4,
          eclo_nights_total: 2,
          access_nights_total: 52,
          score: 9.5,
        },
      ),
    );

    assert.deepEqual(
      rows.map((row) => row.key),
      [
        "overrun_days_total",
        "excess_access_nights_total",
        "eclo_nights_total",
        "access_nights_total",
        "score",
      ],
    );
    assert.equal(rows[0].delta, -2);
    assert.equal(rows[0].tone, "ok");
    assert.equal(rows[0].deltaText, "-2");
    assert.equal(rows[1].tone, "idle");
    assert.equal(rows[3].tone, "idle");
    assert.equal(rows[3].deltaText, "+12");
    assert.equal(rows[4].delta, -3);
    assert.equal(rows[4].deltaText, "-3");
  });

  it("falls back to variant minus baseline when no delta is sent", () => {
    const rows = projectSandboxMetrics({
      baseline: { overrun_days_total: 5 },
      variant: { metrics: { overrun_days_total: 7 } },
      delta: {},
    } as never);
    assert.equal(rows[0].delta, 2);
  });
});

describe("fragilityReading", () => {
  it("says so when no probe was requested", () => {
    const reading = fragilityReading(null);
    assert.equal(reading.present, false);
    assert.equal(reading.tone, "idle");
    assert.match(reading.headline, /No fragility signal/);
  });

  it("flags a one-unit breaking reduction as fragile", () => {
    const reading = fragilityReading({
      location_id: "SEC:A",
      base_supply: 4,
      feasible_floor: 4,
      breaking_new_supply: 3,
      smallest_supply_reduction: 1,
      trials: 3,
      bounded: true,
      note: "breaks",
    });
    assert.equal(reading.present, true);
    assert.equal(reading.tone, "danger");
    assert.equal(reading.breakingSupply, 3);
    assert.equal(reading.smallestReduction, 1);
    assert.match(reading.headline, /breaks at supply 3/);
  });

  it("grades the reduction distance", () => {
    const two = fragilityReading({
      location_id: "SEC:A",
      base_supply: 4,
      feasible_floor: 3,
      breaking_new_supply: 2,
      smallest_supply_reduction: 2,
      trials: 4,
      bounded: true,
      note: "",
    });
    assert.equal(two.tone, "warn");
    const four = fragilityReading({
      location_id: "SEC:A",
      base_supply: 5,
      feasible_floor: 1,
      breaking_new_supply: 0,
      smallest_supply_reduction: 5,
      trials: 5,
      bounded: true,
      note: "",
    });
    assert.equal(four.tone, "ok");
  });

  it("recognises zero base supply and a robust floor", () => {
    const zero = fragilityReading({
      location_id: "SEC:A",
      base_supply: 0,
      feasible_floor: 0,
      breaking_new_supply: null,
      smallest_supply_reduction: null,
      trials: 1,
      bounded: true,
      note: "already zero",
    });
    assert.equal(zero.tone, "idle");
    assert.match(zero.headline, /already has zero supply/);

    const robust = fragilityReading({
      location_id: "SEC:A",
      base_supply: 3,
      feasible_floor: 0,
      breaking_new_supply: null,
      smallest_supply_reduction: null,
      trials: 2,
      bounded: true,
      note: "stays feasible at 0",
    });
    assert.equal(robust.tone, "ok");
  });

  it("reports soft capacity as informational, not fragile", () => {
    const soft = fragilityReading({
      location_id: "SEC:A",
      base_supply: 3,
      feasible_floor: null,
      breaking_new_supply: null,
      smallest_supply_reduction: null,
      trials: 0,
      bounded: true,
      note: "scenario B treats capacity as soft",
    });
    assert.equal(soft.tone, "info");
    assert.match(soft.detail, /soft/);
  });
});

describe("describeApplied", () => {
  it("describes each applied knob in a stable order", () => {
    const parts = describeApplied({
      scenario: "B",
      supply: { "SEC:B": 1, "SEC:A": 2 },
      workfronts: { C1: 3 },
      horizon_extension_weeks: 2,
      eclo_allowed: true,
    });
    assert.deepEqual(parts, [
      "scenario B",
      "supply SEC:A → 2, SEC:B → 1",
      "workfronts C1 → 3",
      "horizon +2 weeks",
      "ECLO allowed",
    ]);
  });

  it("uses the singular for a one-week extension", () => {
    assert.deepEqual(describeApplied({ horizon_extension_weeks: 1 }), [
      "horizon +1 week",
    ]);
  });

  it("is empty when nothing was applied", () => {
    assert.deepEqual(describeApplied({}), []);
  });
});

describe("buildSandboxRequest", () => {
  it("rejects an empty knob set", () => {
    const built = buildSandboxRequest(newSandboxDraft());
    assert.equal(built.ok, false);
    assert.equal(built.payload, null);
    assert.match(built.errors.join(" "), /at least one knob/);
  });

  it("builds a supply override with a zero value", () => {
    const draft = newSandboxDraft();
    draft.supplyLocationId = "SEC:A";
    draft.supplyValue = "0";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, true);
    assert.deepEqual(built.payload?.supply, { "SEC:A": 0 });
  });

  it("rejects a supply override without a location", () => {
    const draft = newSandboxDraft();
    draft.supplyValue = "2";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, false);
    assert.match(built.errors.join(" "), /Choose a location/);
  });

  it("rejects a workfront below one", () => {
    const draft = newSandboxDraft();
    draft.workfrontContract = "C1";
    draft.workfrontValue = "0";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, false);
    assert.match(built.errors.join(" "), /1 or more/);
  });

  it("applies scenario, ECLO, horizon and options", () => {
    const draft = newSandboxDraft();
    draft.scenario = "B";
    draft.ecloAllowed = "false";
    draft.horizonExtensionWeeks = "3";
    draft.timeLimitSeconds = "20";
    draft.seed = "42";
    draft.fragilityMaxTrials = "8";
    draft.fragilityLocationId = "SEC:A";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, true);
    assert.deepEqual(built.payload, {
      scenario: "B",
      horizon_extension_weeks: 3,
      eclo_allowed: false,
      fragility_location_id: "SEC:A",
      time_limit_seconds: 20,
      seed: 42,
      fragility_max_trials: 8,
    });
  });

  it("allows a fragility-only probe to count as a knob", () => {
    const draft = newSandboxDraft();
    draft.fragilityLocationId = "SEC:A";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, true);
    assert.deepEqual(built.payload, {
      fragility_location_id: "SEC:A",
      fragility_max_trials: DEFAULT_FRAGILITY_TRIALS,
    });
  });

  it("validates seed and fragility trial bounds", () => {
    const draft = newSandboxDraft();
    draft.scenario = "A";
    draft.seed = "9999999999";
    draft.fragilityMaxTrials = "1";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, false);
    assert.equal(built.errors.length, 2);
    assert.match(built.errors.join(" "), /Seed must be/);
    assert.match(built.errors.join(" "), /Fragility trials must be/);
  });

  it("rejects a non-positive time limit", () => {
    const draft = newSandboxDraft();
    draft.scenario = "A";
    draft.timeLimitSeconds = "0";
    const built = buildSandboxRequest(draft);
    assert.equal(built.ok, false);
    assert.match(built.errors.join(" "), /Time limit/);
  });
});
