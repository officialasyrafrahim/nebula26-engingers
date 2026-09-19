import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ReplanDiff, ReplanImpact, ReplanRead } from "../src/api/types.ts";
import {
  buildReplanRequest,
  classifyReplanStatus,
  describeDisruption,
  formatChurnCost,
  formatChurnSummary,
  formatSlot,
  formatSlotList,
  isReplanUsable,
  newDisruptionDraft,
  parseWeeks,
  projectMoved,
  replanStatusLabel,
  replanStatusTone,
  summariseDiff,
  summariseImpact,
  validateDisruptionDraft,
  validateReplanDrafts,
  churnShare,
  isIsoDate,
  type DisruptionDraft,
} from "../src/lib/replan.ts";

function draft(overrides: Partial<DisruptionDraft>): DisruptionDraft {
  return { ...newDisruptionDraft("d1"), ...overrides };
}

function diff(overrides: Partial<ReplanDiff> = {}): ReplanDiff {
  return {
    moved: [],
    unchanged: [],
    added: [],
    removed: [],
    newly_unsatisfiable: [],
    totals: {
      original_accesses: 0,
      replan_accesses: 0,
      reused_accesses: 0,
      moved_accesses: 0,
      moved_activities: 0,
      unchanged_activities: 0,
    },
    ...overrides,
  };
}

describe("replan status", () => {
  it("classifies OPTIMAL and FEASIBLE as feasible", () => {
    assert.equal(classifyReplanStatus("OPTIMAL"), "feasible");
    assert.equal(classifyReplanStatus("FEASIBLE"), "feasible");
    assert.equal(classifyReplanStatus("feasible"), "feasible");
  });

  it("classifies the honest failure states", () => {
    assert.equal(classifyReplanStatus("INFEASIBLE"), "infeasible");
    assert.equal(classifyReplanStatus("UNSAFE"), "unsafe");
    assert.equal(classifyReplanStatus("MODEL_INVALID"), "unknown");
    assert.equal(classifyReplanStatus(null), "unknown");
  });

  it("labels statuses and picks a lamp tone", () => {
    assert.equal(replanStatusLabel("OPTIMAL"), "FEASIBLE");
    assert.equal(replanStatusLabel("INFEASIBLE"), "INFEASIBLE");
    assert.equal(replanStatusLabel("UNSAFE"), "UNSAFE");
    assert.equal(replanStatusLabel("TIMED_OUT"), "UNKNOWN");
    assert.equal(replanStatusTone("FEASIBLE"), "ok");
    assert.equal(replanStatusTone("INFEASIBLE"), "danger");
    assert.equal(replanStatusTone("UNSAFE"), "danger");
    assert.equal(replanStatusTone("SOMETHING"), "warn");
  });

  it("only treats safe, feasible outcomes as usable", () => {
    const usable: Pick<ReplanRead, "status" | "safe"> = {
      status: "OPTIMAL",
      safe: true,
    };
    assert.equal(isReplanUsable(usable), true);
    assert.equal(isReplanUsable({ status: "UNSAFE", safe: false }), false);
    assert.equal(isReplanUsable({ status: "INFEASIBLE", safe: false }), false);
    assert.equal(isReplanUsable({ status: "OPTIMAL", safe: false }), false);
    assert.equal(isReplanUsable({ status: "UNKNOWN", safe: true }), false);
    assert.equal(isReplanUsable(null), false);
  });
});

describe("diff summarisation", () => {
  it("summarises the moved, added, removed and unsatisfiable sets", () => {
    const summary = summariseDiff(
      diff({
        moved: [
          {
            activity_id: "A1",
            from: [[1, 2]],
            to: [[3, 4]],
          },
        ],
        unchanged: ["A2", "A3"],
        added: ["U1"],
        removed: ["A4"],
        newly_unsatisfiable: ["A5", "A6"],
        totals: {
          original_accesses: 10,
          replan_accesses: 9,
          reused_accesses: 7,
          moved_accesses: 3,
          moved_activities: 1,
          unchanged_activities: 2,
        },
      }),
    );
    assert.equal(summary.movedActivities, 1);
    assert.equal(summary.movedAccesses, 3);
    assert.equal(summary.unchangedActivities, 2);
    assert.equal(summary.addedActivities, 1);
    assert.equal(summary.removedActivities, 1);
    assert.equal(summary.unsatisfiableActivities, 2);
    assert.equal(summary.originalAccesses, 10);
    assert.equal(summary.reusedAccesses, 7);
    assert.equal(summary.hasChanges, true);
  });

  it("reports no changes for an untouched schedule", () => {
    const summary = summariseDiff(
      diff({ unchanged: ["A1", "A2"], totals: { ...diff().totals } }),
    );
    assert.equal(summary.hasChanges, false);
    assert.equal(summary.movedActivities, 0);
  });

  it("is defensive about a missing diff", () => {
    const summary = summariseDiff(null);
    assert.equal(summary.movedActivities, 0);
    assert.equal(summary.originalAccesses, 0);
    assert.equal(summary.hasChanges, false);
  });

  it("formats slots and projects moved rows", () => {
    assert.equal(formatSlot([2, 5]), "W2·N5");
    assert.equal(formatSlot([4, null]), "W4");
    assert.equal(formatSlot(null), "—");
    assert.equal(formatSlotList([[1, 1], [2, null]]), "W1·N1, W2");
    assert.equal(formatSlotList([]), "—");
    assert.deepEqual(
      projectMoved(
        diff({
          moved: [
            { activity_id: "A1", from: [[1, 1]], to: [[2, null]] },
          ],
        }),
      ),
      [{ activityId: "A1", from: ["W1·N1"], to: ["W2"] }],
    );
  });
});

describe("churn formatting", () => {
  it("formats the churn cost", () => {
    assert.equal(formatChurnCost(0), "No accesses moved");
    assert.equal(formatChurnCost(1), "1 access moved");
    assert.equal(formatChurnCost(4), "4 accesses moved");
    assert.equal(formatChurnCost(null), "No accesses moved");
  });

  it("formats the churn share against the reference", () => {
    assert.equal(churnShare(3, 12), "3 of 12 (25%)");
    assert.equal(churnShare(13, 12), "12 of 12 (100%)");
    assert.equal(churnShare(0, 0), "—");
  });

  it("combines cost and share", () => {
    assert.equal(
      formatChurnSummary(3, 12),
      "3 accesses moved · 3 of 12 (25%)",
    );
    assert.equal(formatChurnSummary(0, 0), "No accesses moved");
  });
});

describe("impact summary", () => {
  it("projects the persisted impact counts", () => {
    const impact: ReplanImpact = {
      invalid_placements: [
        {
          activity_id: "A1",
          week: 1,
          physical_night: 2,
          location_id: "LOC",
          reason: "supply_drop",
        },
      ],
      affected_activities: ["A1"],
      affected_contracts: ["C1"],
      affected_location_weeks: [],
      workload: {
        access_nights_before: 3,
        invalid_access_nights: 1,
        injected_access_nights: 0,
        access_nights_after_lower_bound: 2,
      },
      overrun: {
        overrun_days_before: 0,
        contracts_overrunning_before: 0,
        displaced_access_nights: 1,
        worst_case_additional_overrun_days: 7,
        worst_case_overrun_days: 7,
      },
      notes: [],
    };
    const summary = summariseImpact(impact);
    assert.equal(summary.invalidPlacements, 1);
    assert.equal(summary.affectedActivities, 1);
    assert.equal(summary.affectedContracts, 1);
    assert.equal(summary.accessNightsBefore, 3);
    assert.equal(summary.accessNightsAfter, 2);
  });
});

describe("disruption form validation", () => {
  it("accepts a supply drop with a whole supply value", () => {
    const result = validateDisruptionDraft(
      draft({ kind: "supply_drop", locationId: "LOC", newSupply: "0" }),
    );
    assert.equal(result.ok, true);
    assert.deepEqual(result.disruption, {
      kind: "supply_drop",
      location_id: "LOC",
      new_supply: 0,
    });
  });

  it("rejects a supply drop without a location or a negative supply", () => {
    const result = validateDisruptionDraft(
      draft({ kind: "supply_drop", locationId: " ", newSupply: "-1" }),
    );
    assert.equal(result.ok, false);
    assert.equal(result.errors.length, 2);
  });

  it("parses optional weeks and defaults to the whole horizon", () => {
    assert.deepEqual(parseWeeks(""), { weeks: null, error: null });
    assert.deepEqual(parseWeeks("1, 3, 3 2"), { weeks: [1, 2, 3], error: null });
    assert.equal(parseWeeks("one").error !== null, true);
    assert.equal(parseWeeks("0").error !== null, true);
  });

  it("builds a location closure with and without weeks", () => {
    const whole = validateDisruptionDraft(
      draft({ kind: "location_unavailable", locationId: "LOC", weeks: "" }),
    );
    assert.deepEqual(whole.disruption, {
      kind: "location_unavailable",
      location_id: "LOC",
      weeks: null,
    });
    const partial = validateDisruptionDraft(
      draft({
        kind: "location_unavailable",
        locationId: "LOC",
        weeks: "2,4",
      }),
    );
    assert.deepEqual(partial.disruption, {
      kind: "location_unavailable",
      location_id: "LOC",
      weeks: [2, 4],
    });
  });

  it("bounds the physical night to 1..7", () => {
    const valid = validateDisruptionDraft(
      draft({ kind: "night_unavailable", physicalNight: "7", weeks: "1" }),
    );
    assert.deepEqual(valid.disruption, {
      kind: "night_unavailable",
      physical_night: 7,
      weeks: [1],
    });
    const invalid = validateDisruptionDraft(
      draft({ kind: "night_unavailable", physicalNight: "8", weeks: "" }),
    );
    assert.equal(invalid.ok, false);
  });

  it("builds an urgent activity injection and nulls optional blanks", () => {
    const result = validateDisruptionDraft(
      draft({
        kind: "urgent_activity",
        activityId: "U1",
        contractNumber: "C1",
        startLocationId: "A",
        endLocationId: "B",
        totalAccesses: "2",
        activityPriority: "3",
        plannedStartDate: "2026-03-02",
        activityType: "",
        predecessorActivityId: "",
      }),
    );
    assert.equal(result.ok, true);
    assert.deepEqual(result.disruption, {
      kind: "urgent_activity",
      activity_id: "U1",
      contract_number: "C1",
      activity_type: null,
      start_location_id: "A",
      end_location_id: "B",
      total_accesses: 2,
      planned_start_date: "2026-03-02",
      predecessor_activity_id: null,
      activity_priority: 3,
    });
  });

  it("rejects an impossible calendar date and out of range priority", () => {
    assert.equal(isIsoDate("2026-02-30"), false);
    assert.equal(isIsoDate("2026-02-28"), true);
    assert.equal(isIsoDate("28/02/2026"), false);
    const result = validateDisruptionDraft(
      draft({
        kind: "urgent_activity",
        activityId: "U1",
        contractNumber: "C1",
        startLocationId: "A",
        endLocationId: "B",
        totalAccesses: "0",
        activityPriority: "9",
        plannedStartDate: "2026-02-30",
      }),
    );
    assert.equal(result.ok, false);
    assert.equal(result.errors.length, 3);
  });

  it("requires at least one disruption", () => {
    const result = validateReplanDrafts([]);
    assert.equal(result.ok, false);
    assert.equal(result.errors.length, 1);
  });

  it("prefixes per-draft errors with the draft number", () => {
    const result = validateReplanDrafts([
      draft({ id: "a", kind: "supply_drop", locationId: "LOC" }),
      draft({ id: "b", kind: "night_unavailable", physicalNight: "9" }),
    ]);
    assert.equal(result.ok, false);
    assert.equal(result.disruptions.length, 1);
    assert.equal(result.errors[0].startsWith("Disruption 2:"), true);
  });
});

describe("buildReplanRequest", () => {
  const validDraft = draft({
    kind: "supply_drop",
    locationId: "LOC",
    newSupply: "1",
  });

  it("builds a minimal payload with blank options omitted", () => {
    const result = buildReplanRequest([validDraft], {
      timeLimitSeconds: "",
      seed: "",
      horizonExtensionWeeks: "",
    });
    assert.equal(result.ok, true);
    assert.deepEqual(result.payload, {
      disruptions: [
        { kind: "supply_drop", location_id: "LOC", new_supply: 1 },
      ],
    });
  });

  it("includes parsed options when present", () => {
    const result = buildReplanRequest([validDraft], {
      timeLimitSeconds: "5",
      seed: "42",
      horizonExtensionWeeks: "0",
    });
    assert.equal(result.payload?.time_limit_seconds, 5);
    assert.equal(result.payload?.seed, 42);
    assert.equal(result.payload?.horizon_extension_weeks, 0);
  });

  it("rejects a malformed option and withholds the payload", () => {
    const result = buildReplanRequest([validDraft], {
      timeLimitSeconds: "0",
      seed: "abc",
      horizonExtensionWeeks: "-1",
    });
    assert.equal(result.ok, false);
    assert.equal(result.payload, null);
    assert.equal(result.errors.length, 3);
  });
});

describe("describeDisruption", () => {
  it("describes each kind for the composed list", () => {
    assert.equal(
      describeDisruption({
        kind: "supply_drop",
        location_id: "LOC",
        new_supply: 2,
      }),
      "Supply drop LOC → 2",
    );
    assert.equal(
      describeDisruption({
        kind: "location_unavailable",
        location_id: "LOC",
        weeks: null,
      }),
      "Close LOC all weeks",
    );
    assert.equal(
      describeDisruption({
        kind: "night_unavailable",
        physical_night: 3,
        weeks: [1, 2],
      }),
      "Close night 3 weeks 1, 2",
    );
    assert.equal(
      describeDisruption({
        kind: "urgent_activity",
        activity_id: "U1",
        contract_number: "C1",
        start_location_id: "A",
        end_location_id: "B",
        total_accesses: 1,
        planned_start_date: "2026-03-02",
        activity_priority: 1,
      }),
      "Inject U1 (C1) ×1",
    );
  });
});
