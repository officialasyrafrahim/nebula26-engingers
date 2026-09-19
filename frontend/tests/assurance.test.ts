import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { checkDetailText } from "../src/lib/assurance.ts";

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
