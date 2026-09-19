import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  displacementReading,
  evidenceIsNeutral,
  isConfirmingEvidence,
  reasonEvidenceKeys,
  reasonSupport,
} from "../src/lib/explanations.ts";

describe("isConfirmingEvidence", () => {
  it("rejects false, zero, empty strings and empty collections", () => {
    assert.equal(isConfirmingEvidence(false), false);
    assert.equal(isConfirmingEvidence(0), false);
    assert.equal(isConfirmingEvidence(""), false);
    assert.equal(isConfirmingEvidence([]), false);
    assert.equal(isConfirmingEvidence({}), false);
    assert.equal(isConfirmingEvidence(null), false);
    assert.equal(isConfirmingEvidence(undefined), false);
  });

  it("accepts true, positive numbers, text and populated collections", () => {
    assert.equal(isConfirmingEvidence(true), true);
    assert.equal(isConfirmingEvidence(3), true);
    assert.equal(isConfirmingEvidence("closure"), true);
    assert.equal(isConfirmingEvidence(["g1"]), true);
    assert.equal(isConfirmingEvidence({ used: 2 }), true);
  });
});

describe("reasonSupport", () => {
  it("supports BUFFER_CLOSURE from the closure count when buffer_sectors is 0", () => {
    const support = reasonSupport(
      { buffer_sectors: 0, closure_location_count: 1 },
      ["BUFFER_CLOSURE"],
    );
    assert.deepEqual(support.supported, ["BUFFER_CLOSURE"]);
    assert.deepEqual(support.unsupported, []);
  });

  it("supports LIVE_MIRROR from the count when opposite_bound_required is false", () => {
    const support = reasonSupport(
      { opposite_bound_required: false, mirrored_location_count: 2 },
      ["LIVE_MIRROR"],
    );
    assert.deepEqual(support.supported, ["LIVE_MIRROR"]);
  });

  it("reports INTERCHANGE unsupported when its only count is zero", () => {
    const support = reasonSupport(
      { interchange_location_count: 0 },
      ["INTERCHANGE"],
    );
    assert.deepEqual(support.supported, []);
    assert.deepEqual(support.unsupported, ["INTERCHANGE"]);
  });

  it("reports CO_SHARE_PACKED unsupported when every fact is empty", () => {
    const support = reasonSupport(
      { co_share_group: "", co_share_partners: [] },
      ["CO_SHARE_PACKED"],
    );
    assert.deepEqual(support.unsupported, ["CO_SHARE_PACKED"]);
  });

  it("treats codes without required facts as supported", () => {
    const support = reasonSupport({}, ["PREDECESSOR", "PLANNED_START"]);
    assert.deepEqual(support.supported, ["PREDECESSOR", "PLANNED_START"]);
    assert.deepEqual(support.unsupported, []);
  });
});

describe("reasonEvidenceKeys", () => {
  it("collects only the keys tied to the present reason codes", () => {
    const keys = reasonEvidenceKeys(["LIVE_MIRROR", "INTERCHANGE"]);
    assert.equal(keys.has("opposite_bound_required"), true);
    assert.equal(keys.has("mirrored_location_count"), true);
    assert.equal(keys.has("interchange_location_count"), true);
    assert.equal(keys.has("buffer_sectors"), false);
  });
});

describe("evidenceIsNeutral", () => {
  const keys = reasonEvidenceKeys(["BUFFER_CLOSURE"]);

  it("marks a zero counterpart fact as neutral", () => {
    assert.equal(evidenceIsNeutral("buffer_sectors", 0, keys), true);
  });

  it("does not mark a confirming fact as neutral", () => {
    assert.equal(evidenceIsNeutral("closure_location_count", 1, keys), false);
  });

  it("does not mark unrelated facts as neutral", () => {
    assert.equal(evidenceIsNeutral("horizon_extended", false, keys), false);
  });
});

describe("displacementReading", () => {
  it("says so when no displacement evidence is persisted", () => {
    const reading = displacementReading({ first_week: 3 });
    assert.equal(reading.present, false);
    assert.equal(reading.displaced, false);
    assert.match(reading.note, /No displacement evidence is persisted/);
  });

  it("names a confirmed binding constraint when the evidence is complete", () => {
    const reading = displacementReading({
      displaced: true,
      planned_earliest_week: 1,
      actual_first_week: 3,
      rejected_weeks: [1, 2],
      binding_week: 1,
      binding_constraints: ["CAPACITY"],
      binding_details: {
        CAPACITY: {
          week: 1,
          night: 4,
          location_id: "SEC:ALP:S01_S02:EB",
          used: 1,
          capacity: 1,
        },
      },
    });
    assert.equal(reading.present, true);
    assert.equal(reading.displaced, true);
    assert.deepEqual(reading.supportedConstraints, ["CAPACITY"]);
    assert.deepEqual(reading.unsupportedConstraints, []);
    assert.equal(reading.trustworthy, true);
    assert.match(reading.note, /earliest admissible week was blocked/);
  });

  it("refuses to name a constraint whose detail does not confirm it", () => {
    const reading = displacementReading({
      displaced: true,
      planned_earliest_week: 1,
      actual_first_week: 3,
      rejected_weeks: [1, 2],
      binding_week: 1,
      binding_constraints: ["CAPACITY"],
      binding_details: {},
    });
    assert.deepEqual(reading.supportedConstraints, []);
    assert.deepEqual(reading.unsupportedConstraints, ["CAPACITY"]);
    assert.equal(reading.trustworthy, false);
    assert.match(reading.note, /incomplete or inconsistent/);
  });

  it("distrusts a binding week that was never rejected", () => {
    const reading = displacementReading({
      displaced: true,
      planned_earliest_week: 1,
      actual_first_week: 3,
      rejected_weeks: [2],
      binding_week: 1,
      binding_constraints: ["WEEKLY_CAP"],
      binding_details: { WEEKLY_CAP: { week: 1, used: 2, limit: 2 } },
    });
    assert.equal(reading.trustworthy, false);
  });

  it("reports an undisplaced placement without claiming a cause", () => {
    const reading = displacementReading({
      displaced: false,
      planned_earliest_week: 3,
      actual_first_week: 3,
    });
    assert.equal(reading.present, true);
    assert.equal(reading.displaced, false);
    assert.equal(reading.trustworthy, false);
    assert.match(reading.note, /No earlier week was rejected/);
  });
});
