import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { checkDetailText, deriveAssurance } from "../src/lib/assurance.ts";

describe("checkDetailText", () => {
  it("shows soft capacity excess when there are no hard violations", () => {
    assert.equal(
      checkDetailText({
        hard_violations: [],
        soft_excess: [{ location_id: "S1", excess: 1 }],
        soft_excess_total: 1,
      }),
      "1 soft excess issue(s)",
    );
  });

  it("shows none when every issue collection is empty", () => {
    assert.equal(
      checkDetailText({
        hard_violations: [],
        soft_excess: [],
        soft_excess_total: 0,
      }),
      "none",
    );
  });
});

describe("deriveAssurance", () => {
  const base = {
    authority: "fallback",
    validatorSource: "fallback",
    feasible: true,
    workloadComplete: true,
    physical: "pass" as const,
  };

  it("marks an official pass with physical checks as officially validated", () => {
    const outcome = deriveAssurance({
      ...base,
      authority: "official",
      validatorSource: "official",
    });
    assert.equal(outcome.status, "OFFICIALLY VALIDATED");
    assert.equal(outcome.official, "pass");
    assert.equal(outcome.fallback, "unavailable");
  });

  it("keeps a fallback pass provisional, never official", () => {
    const outcome = deriveAssurance(base);
    assert.equal(outcome.status, "PROVISIONAL");
    assert.equal(outcome.fallback, "pass");
    assert.equal(outcome.official, "unavailable");
  });

  it("does not claim provisional status without physical checks", () => {
    const outcome = deriveAssurance({ ...base, physical: "unavailable" });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.ok(
      outcome.failingLayers.some((layer) => layer.includes("physical")),
    );
  });

  it("treats an authority/source disagreement as not validated", () => {
    const outcome = deriveAssurance({
      ...base,
      authority: "official",
      validatorSource: "fallback",
    });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.equal(outcome.authorityMismatch, true);
    assert.equal(outcome.official, "unavailable");
    assert.equal(outcome.fallback, "unavailable");
  });

  it("does not blame the fallback for an unrecognised authority", () => {
    const outcome = deriveAssurance({
      ...base,
      authority: "mystery",
      validatorSource: "mystery",
    });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.ok(
      outcome.failingLayers.some((layer) =>
        layer.includes("unrecognised validation authority"),
      ),
    );
    assert.equal(
      outcome.failingLayers.some((layer) =>
        layer.includes("fallback schema validation"),
      ),
      false,
    );
  });

  it("names only the physical layer when a passing fallback is the sole other layer", () => {
    const outcome = deriveAssurance({ ...base, physical: "fail" });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.equal(outcome.fallback, "pass");
    assert.deepEqual(outcome.failingLayers, ["physical schedule checks"]);
    assert.equal(
      outcome.failingLayers.some((layer) =>
        layer.includes("fallback schema validation"),
      ),
      false,
    );
  });

  it("excludes a passing official layer from failing layers", () => {
    const outcome = deriveAssurance({
      ...base,
      authority: "official",
      validatorSource: "official",
      physical: "fail",
    });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.equal(outcome.official, "pass");
    assert.deepEqual(outcome.failingLayers, ["physical schedule checks"]);
  });

  it("still names a validator layer that actually failed", () => {
    const outcome = deriveAssurance({
      ...base,
      feasible: false,
      physical: "fail",
    });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.equal(outcome.fallback, "fail");
    assert.deepEqual(outcome.failingLayers, [
      "physical schedule checks",
      "fallback schema validation",
    ]);
  });

  it("names a rejected official layer even when physical checks pass", () => {
    const outcome = deriveAssurance({
      ...base,
      authority: "official",
      validatorSource: "official",
      workloadComplete: false,
    });
    assert.equal(outcome.status, "NOT VALIDATED");
    assert.equal(outcome.official, "fail");
    assert.deepEqual(outcome.failingLayers, ["official validation"]);
  });
});
