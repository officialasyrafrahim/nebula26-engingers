import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type {
  NetworkResponse,
  ScheduleAccess,
  ScheduleOccupancy,
  ScheduleResponse,
} from "../src/api/types.ts";
import { tonightSummary } from "../src/lib/tonight.ts";

function network(partial: Partial<NetworkResponse>): NetworkResponse {
  return {
    parameters: {},
    lines: [{ line_code: "ALP", line_name: "ALP" }],
    stations: [
      { station_id: "S01", line_code: "ALP", seq: 1, is_interchange: false },
      { station_id: "S02", line_code: "ALP", seq: 2, is_interchange: false },
    ],
    sectors: [
      {
        sector_id: "S01_S02",
        line_code: "ALP",
        from_station_id: "S01",
        to_station_id: "S02",
        seq: 1,
        is_shared: false,
      },
    ],
    locations: [
      {
        location_id: "PLAT:ALP:S01:EB",
        location_kind: "platform",
        line_code: "ALP",
        bound: "EB",
        supply_capacity: 1,
      },
    ],
    buffer_rules: [],
    contracts: [
      {
        contract_number: "C1",
        contract_description: "Newton to Little India",
        contract_award_date: "2027-01-01",
        activity_type: "Track",
        nature_of_activity: "Non-live (Others)",
        contract_priority: 1,
        contract_completion_date: "2027-03-01",
        planned_completion_date: "2027-03-01",
        number_of_workfronts: 1,
        access_type: "PC",
        number_of_maximum_access_per_week: 2,
      },
      {
        contract_number: "C2",
        contract_description: "Little India to Newton",
        contract_award_date: "2027-01-01",
        activity_type: "Track",
        nature_of_activity: "Live",
        contract_priority: 2,
        contract_completion_date: "2027-03-01",
        planned_completion_date: "2027-03-01",
        number_of_workfronts: 2,
        access_type: "C",
        number_of_maximum_access_per_week: 2,
      },
    ],
    activities: [
      {
        activity_id: "A001",
        contract_number: "C1",
        activity_type: "Track",
        start_location_id: "PLAT:ALP:S01:EB",
        end_location_id: "PLAT:ALP:S02:EB",
        total_accesses: 2,
        planned_start_date: "2027-01-04",
        predecessor_activity_id: null,
        activity_priority: 1,
      },
      {
        activity_id: "A002",
        contract_number: "C2",
        activity_type: "Track",
        start_location_id: "PLAT:ALP:S02:EB",
        end_location_id: "PLAT:ALP:S01:EB",
        total_accesses: 2,
        planned_start_date: "2027-01-04",
        predecessor_activity_id: null,
        activity_priority: 2,
      },
      {
        activity_id: "A003",
        contract_number: "C1",
        activity_type: "Track",
        start_location_id: "PLAT:ALP:S01:EB",
        end_location_id: "PLAT:ALP:S02:EB",
        total_accesses: 1,
        planned_start_date: "2027-01-11",
        predecessor_activity_id: null,
        activity_priority: 1,
      },
    ],
    routes: {},
    location_capacities: { "PLAT:ALP:S01:EB": 1 },
    activity_spans: {
      A001: {
        occupied_locations: ["PLAT:ALP:S01:EB"],
        closure_locations: ["PLAT:ALP:S01:EB", "SEC:ALP:S01_S02:EB"],
        mirrored_locations: ["PLAT:ALP:S01:WB"],
        interchange_locations: ["PLAT:ALP:S02:EB"],
      },
    },
    ...partial,
  };
}

function accessRow(
  activityId: string,
  week: number,
  accessNight: number,
  eclo = false,
  physicalNight: number | null = null,
): ScheduleAccess {
  return {
    id: `${activityId}-${week}-${accessNight}`,
    activity_id: activityId,
    access_seq: 1,
    week,
    eclo,
    access_night: accessNight,
    physical_night: physicalNight,
  };
}

function occupancyRow(
  activityId: string,
  week: number,
  locationId: string,
  group: string,
): ScheduleOccupancy {
  return {
    id: `${activityId}-${week}-${locationId}`,
    activity_id: activityId,
    week,
    location_id: locationId,
    co_share_group: group,
  };
}

function schedule(partial: Partial<ScheduleResponse>): ScheduleResponse {
  return {
    run_id: "run-1",
    job_id: "job-1",
    scenario: "A",
    access: [],
    occupancy: [],
    results: [],
    explanations: [],
    ...partial,
  };
}

const baseSchedule = schedule({
  access: [
    accessRow("A001", 1, 2),
    accessRow("A002", 1, 5),
    accessRow("A003", 2, 3),
  ],
  occupancy: [
    occupancyRow("A001", 1, "PLAT:ALP:S01:EB", "g1"),
    occupancyRow("A002", 1, "PLAT:ALP:S01:EB", "g2"),
  ],
});

describe("tonightSummary workfronts", () => {
  it("groups the placed activities by contract for the selected week", () => {
    const summary = tonightSummary(network({}), baseSchedule, 1, null, "A");
    assert.deepEqual(summary.activityIds, ["A001", "A002"]);
    assert.deepEqual(
      summary.workfronts.map((workfront) => workfront.contractNumber),
      ["C1", "C2"],
    );
    const c1 = summary.workfronts.find((entry) => entry.contractNumber === "C1")!;
    assert.deepEqual(c1.activityIds, ["A001"]);
    assert.equal(c1.concurrentWorkfronts, 1);
    const c2 = summary.workfronts.find((entry) => entry.contractNumber === "C2")!;
    assert.deepEqual(c2.activityIds, ["A002"]);
    assert.equal(c2.concurrentWorkfronts, 2);
    assert.equal(c2.nature, "Live");
  });

  it("narrows to a single night when one is selected", () => {
    const summary = tonightSummary(network({}), baseSchedule, 1, 5, "A");
    assert.deepEqual(summary.activityIds, ["A002"]);
    assert.deepEqual(
      summary.workfronts.map((workfront) => workfront.contractNumber),
      ["C2"],
    );
  });
});

describe("tonightSummary attention", () => {
  it("reads buffer, mirror, interchange and capacity from persisted rows", () => {
    const summary = tonightSummary(network({}), baseSchedule, 1, null, "A");
    const kinds = summary.attention.map((item) => item.kind);
    assert.ok(kinds.includes("buffer"));
    assert.ok(kinds.includes("mirror"));
    assert.ok(kinds.includes("interchange"));
    assert.ok(kinds.includes("capacity"));

    const buffer = summary.attention.find((item) => item.kind === "buffer")!;
    assert.equal(buffer.locationId, "SEC:ALP:S01_S02:EB");
    assert.equal(buffer.label, "Newton–Little India");
    assert.equal(buffer.mapped, true);
    assert.deepEqual(buffer.activityIds, ["A001"]);

    const capacity = summary.attention.find((item) => item.kind === "capacity")!;
    assert.equal(capacity.locationId, "PLAT:ALP:S01:EB");
    assert.match(capacity.detail, /2\/1/);
  });

  it("leaves the span layers out when the run publishes no spans", () => {
    const summary = tonightSummary(
      network({ activity_spans: null }),
      baseSchedule,
      1,
      null,
      "A",
    );
    assert.deepEqual(
      summary.attention.filter((item) => item.kind !== "capacity"),
      [],
    );
  });
});

describe("tonightSummary handbacks", () => {
  it("reports what finishes this week and what starts next week", () => {
    const summary = tonightSummary(network({}), baseSchedule, 1, null, "A");
    assert.deepEqual(
      summary.finishing.map((item) => item.activityId),
      ["A001", "A002"],
    );
    assert.deepEqual(
      summary.startingNext.map((item) => item.activityId),
      ["A003"],
    );
    assert.equal(summary.startingNext[0].week, 2);
  });

  it("reports the night source as contract-local without a physical slot", () => {
    const summary = tonightSummary(network({}), baseSchedule, 1, null, "A");
    assert.equal(summary.nightSource, "local");
  });

  it("reports the physical night source when the API publishes slots", () => {
    const physical = schedule({
      access: [accessRow("A001", 1, 2, false, 7)],
      occupancy: [occupancyRow("A001", 1, "PLAT:ALP:S01:EB", "g1")],
    });
    const summary = tonightSummary(network({}), physical, 1, null, "A");
    assert.equal(summary.nightSource, "physical");
  });
});
