import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  lineDisplay,
  locationDisplay,
  sectorDisplay,
  stationDisplay,
} from "../src/lib/networkNames.ts";

describe("lineDisplay", () => {
  it("maps the solver line codes to the DTL and CCL presentation codes", () => {
    assert.deepEqual(lineDisplay("ALP"), {
      text: "DTL",
      name: "Downtown Line",
      mapped: true,
    });
    assert.deepEqual(lineDisplay("BET"), {
      text: "CCL",
      name: "Circle Line",
      mapped: true,
    });
  });

  it("falls back to the raw code for an unmapped line", () => {
    assert.deepEqual(lineDisplay("XYZ"), {
      text: "XYZ",
      name: "XYZ",
      mapped: false,
    });
  });
});

describe("stationDisplay", () => {
  it("maps ALP and BET stations to their documented names", () => {
    assert.deepEqual(stationDisplay("ALP", "S01"), {
      text: "Newton",
      mapped: true,
    });
    assert.deepEqual(stationDisplay("BET", "S11"), {
      text: "Dakota",
      mapped: true,
    });
    assert.deepEqual(stationDisplay("BET", "S18"), {
      text: "Keppel",
      mapped: true,
    });
  });

  it("shares the interchange hubs across both lines", () => {
    assert.deepEqual(stationDisplay("ALP", "H01"), {
      text: "Promenade",
      mapped: true,
    });
    assert.deepEqual(stationDisplay("BET", "H01"), {
      text: "Promenade",
      mapped: true,
    });
    assert.deepEqual(stationDisplay("ALP", "H02"), {
      text: "Bayfront",
      mapped: true,
    });
  });

  it("keeps the raw identifier for a hidden instance station", () => {
    assert.deepEqual(stationDisplay("HIDDEN", "Q9"), {
      text: "Q9",
      mapped: false,
    });
    assert.deepEqual(stationDisplay("ALP", "S99"), {
      text: "S99",
      mapped: false,
    });
  });
});

describe("sectorDisplay", () => {
  it("joins the two mapped station names", () => {
    assert.deepEqual(sectorDisplay("ALP", "S01_S02"), {
      text: "Newton–Little India",
      mapped: true,
    });
    assert.deepEqual(sectorDisplay("BET", "H01_H02"), {
      text: "Promenade–Bayfront",
      mapped: true,
    });
  });

  it("marks a sector with any unmapped end as unmapped", () => {
    assert.deepEqual(sectorDisplay("ALP", "S01_S99"), {
      text: "Newton–S99",
      mapped: false,
    });
  });

  it("falls back to the raw sector id when the shape is unexpected", () => {
    assert.deepEqual(sectorDisplay("ALP", "NOSEPARATOR"), {
      text: "NOSEPARATOR",
      mapped: false,
    });
  });
});

describe("locationDisplay", () => {
  it("reads a platform location", () => {
    assert.deepEqual(locationDisplay("PLAT:ALP:H01:EB"), {
      text: "Promenade",
      mapped: true,
    });
  });

  it("reads a sector location", () => {
    assert.deepEqual(locationDisplay("SEC:BET:S11_S12:EB"), {
      text: "Dakota–Mountbatten",
      mapped: true,
    });
  });

  it("degrades to the raw id for an unknown location shape", () => {
    assert.deepEqual(locationDisplay("PLAT:HIDDEN:Q9:EB"), {
      text: "Q9",
      mapped: false,
    });
    assert.deepEqual(locationDisplay("garbage"), {
      text: "garbage",
      mapped: false,
    });
  });
});
