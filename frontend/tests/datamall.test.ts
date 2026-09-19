import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { NetworkResponse } from "../src/api/types.ts";
import {
  contextUnavailable,
  crowdLevelLabel,
  crowdLevelTone,
  datamallContextForNetwork,
  datamallStation,
  DATAMALL_NETWORK_KEY,
  DATAMALL_UNAVAILABLE_REASON,
  sourceUnavailable,
} from "../src/lib/datamall.ts";

function network(partial: Partial<NetworkResponse>): NetworkResponse {
  return {
    parameters: {},
    lines: [],
    stations: [],
    sectors: [],
    locations: [],
    buffer_rules: [],
    contracts: [],
    activities: [],
    routes: {},
    location_capacities: {},
    ...partial,
  };
}

const DEMO_NETWORK = network({
  lines: [
    { line_code: "ALP", line_name: "Line Alpha" },
    { line_code: "BET", line_name: "Line Beta" },
  ],
  stations: [
    { station_id: "S01", line_code: "ALP", seq: 1, is_interchange: false },
    { station_id: "H01", line_code: "ALP", seq: 5, is_interchange: true },
    { station_id: "H02", line_code: "ALP", seq: 6, is_interchange: true },
    { station_id: "S11", line_code: "BET", seq: 1, is_interchange: false },
    { station_id: "H01", line_code: "BET", seq: 5, is_interchange: true },
    { station_id: "S15", line_code: "BET", seq: 7, is_interchange: false },
  ],
});

describe("datamallStation", () => {
  it("maps solver ids to public DataMall station codes", () => {
    assert.deepEqual(datamallStation("ALP", "S01"), {
      solverLine: "ALP",
      solverStation: "S01",
      name: "Newton",
      code: "DT11",
      line: "DTL",
    });
    assert.deepEqual(datamallStation("BET", "S11")?.code, "CC8");
    assert.deepEqual(datamallStation("BET", "S18")?.code, "CC30");
  });

  it("gives the interchange hubs a code per line", () => {
    assert.equal(datamallStation("ALP", "H01")?.code, "DT15");
    assert.equal(datamallStation("BET", "H01")?.code, "CC4");
    assert.equal(datamallStation("ALP", "H02")?.code, "DT16");
    assert.equal(datamallStation("BET", "H02")?.code, "CE1");
    assert.equal(datamallStation("BET", "S15")?.code, "CE2");
  });

  it("returns null for an unknown line or station", () => {
    assert.equal(datamallStation("HIDDEN", "Q9"), null);
    assert.equal(datamallStation("ALP", "S99"), null);
  });
});

describe("datamallContextForNetwork", () => {
  it("supports the mapped DTL/CCL demo network", () => {
    const context = datamallContextForNetwork(DEMO_NETWORK);
    assert.equal(context.supported, true);
    assert.equal(context.reason, null);
    assert.equal(context.network, DATAMALL_NETWORK_KEY);
    assert.deepEqual(context.solverLines, ["ALP", "BET"]);
    assert.deepEqual(context.crowdLines, ["DTL", "CCL", "CEL"]);
    assert.equal(context.stations.length, 6);
    assert.deepEqual(context.unmapped, []);
  });

  it("degrades an unmapped hidden network with no guessed codes", () => {
    const hidden = network({
      lines: [{ line_code: "HIDDEN", line_name: "Hidden" }],
      stations: [
        { station_id: "Q9", line_code: "HIDDEN", seq: 1, is_interchange: false },
      ],
    });
    const context = datamallContextForNetwork(hidden);
    assert.equal(context.supported, false);
    assert.equal(context.reason, DATAMALL_UNAVAILABLE_REASON);
    assert.equal(context.network, null);
    assert.deepEqual(context.crowdLines, []);
    assert.deepEqual(context.stations, []);
    assert.deepEqual(context.unmapped, ["HIDDEN", "HIDDEN:Q9"]);
  });

  it("treats a network with no lines as unsupported", () => {
    const empty = datamallContextForNetwork(network({}));
    assert.equal(empty.supported, false);
    assert.equal(empty.reason, DATAMALL_UNAVAILABLE_REASON);
  });
});

describe("crowd levels", () => {
  it("labels the LTA bands without implying occupancy", () => {
    assert.equal(crowdLevelLabel("l"), "Low");
    assert.equal(crowdLevelLabel("m"), "Moderate");
    assert.equal(crowdLevelLabel("h"), "High");
    assert.equal(crowdLevelLabel("NA"), "Unknown");
    assert.equal(crowdLevelLabel("??"), "Unknown");
  });

  it("maps bands to control-board tones", () => {
    assert.equal(crowdLevelTone("l"), "ok");
    assert.equal(crowdLevelTone("m"), "warn");
    assert.equal(crowdLevelTone("h"), "danger");
    assert.equal(crowdLevelTone("NA"), "idle");
  });
});

describe("unavailable-state logic", () => {
  it("treats unconfigured and error sources as unavailable", () => {
    assert.equal(sourceUnavailable("unconfigured"), true);
    assert.equal(sourceUnavailable("error"), true);
    assert.equal(sourceUnavailable("ok"), false);
    assert.equal(sourceUnavailable("empty"), false);
  });

  it("reports an unsupported network as context-unavailable", () => {
    assert.equal(
      contextUnavailable({ supported: false, sources: [{ state: "ok" }] }),
      true,
    );
  });

  it("reports unavailable only when every source is down", () => {
    assert.equal(
      contextUnavailable({
        supported: true,
        sources: [{ state: "unconfigured" }, { state: "error" }],
      }),
      true,
    );
    assert.equal(
      contextUnavailable({
        supported: true,
        sources: [{ state: "unconfigured" }, { state: "ok" }],
      }),
      false,
    );
  });

  it("reports an empty source list as unavailable", () => {
    assert.equal(contextUnavailable({ supported: true, sources: [] }), true);
  });
});
