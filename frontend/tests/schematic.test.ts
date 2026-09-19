import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type {
  NetworkResponse,
  ScheduleAccess,
  ScheduleOccupancy,
} from "../src/api/types.ts";
import {
  capacityReadings,
  coShareMemberships,
  isAtCapacity,
  linesForActivity,
  selectionForPossession,
  spanOverlays,
} from "../src/lib/schematic.ts";

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

describe("spanOverlays safety buffer", () => {
  it("does not paint a buffer on a Non-live Others closure that repeats the route", () => {
    const occupied = ["SEC:ALP:H01_H02:EB", "PLAT:ALP:H01:EB"];
    const overlays = spanOverlays(
      network({
        activity_spans: {
          A_OTHERS: {
            occupied_locations: occupied,
            closure_locations: [...occupied],
            mirrored_locations: [],
            interchange_locations: [],
          },
        },
      }),
      ["A_OTHERS"],
    );

    assert.equal(overlays.available, true);
    assert.equal(overlays.byLocation.size, 0);
  });

  it("keeps only buffer locations outside the occupied route", () => {
    const overlays = spanOverlays(
      network({
        activity_spans: {
          A_LIVE: {
            occupied_locations: ["PLAT:ALP:H02:EB"],
            closure_locations: ["PLAT:ALP:H02:EB", "SEC:ALP:H01_H02:EB"],
            mirrored_locations: ["PLAT:ALP:H02:WB"],
            interchange_locations: ["PLAT:BET:H01:EB"],
          },
        },
      }),
      ["A_LIVE"],
    );

    const bufferLocations = [...overlays.byLocation]
      .filter(([, layers]) => layers.has("buffer"))
      .map(([locationId]) => locationId);
    assert.deepEqual(bufferLocations, ["SEC:ALP:H01_H02:EB"]);
    assert.equal(
      overlays.byLocation.get("PLAT:ALP:H02:EB")?.has("buffer"),
      undefined,
    );
    assert.equal(overlays.byLocation.get("PLAT:ALP:H02:WB")?.has("mirror"), true);
    assert.equal(
      overlays.byLocation.get("PLAT:BET:H01:EB")?.has("interchange"),
      true,
    );
  });
});

describe("linesForActivity", () => {
  it("counts the occupied route line and the cross-line interchange line", () => {
    const lines = linesForActivity(
      network({
        routes: { A1: ["SEC:ALP:H01_H02:EB"] },
        activity_spans: {
          A1: {
            occupied_locations: ["SEC:ALP:H01_H02:EB"],
            closure_locations: [],
            mirrored_locations: [],
            interchange_locations: ["PLAT:BET:H01:EB"],
          },
        },
      }),
      "A1",
    );

    assert.deepEqual(lines, ["ALP", "BET"]);
  });

  it("falls back to the start and end locations when no route is published", () => {
    const lines = linesForActivity(
      network({
        activities: [
          {
            activity_id: "A2",
            contract_number: "C1",
            activity_type: "standard",
            start_location_id: "PLAT:ALP:H01:EB",
            end_location_id: "PLAT:ALP:H02:EB",
            total_accesses: 1,
            planned_start_date: "2027-01-04",
            predecessor_activity_id: null,
            activity_priority: 1,
          },
        ],
      }),
      "A2",
    );

    assert.deepEqual(lines, ["ALP"]);
  });
});

describe("selectionForPossession", () => {
  it("prefers the possession's own night over the board's active night", () => {
    assert.deepEqual(
      selectionForPossession({ activityId: "A1", night: 3, eclo: false }, 4, 7),
      { activityId: "A1", week: 4, night: 3 },
    );
  });

  it("falls back to the active night when the member has none", () => {
    assert.deepEqual(
      selectionForPossession({ activityId: "A1", night: null, eclo: false }, 4, 7),
      { activityId: "A1", week: 4, night: 7 },
    );
  });
});

function accessRow(
  activityId: string,
  week: number,
  accessNight: number,
  physicalNight?: number,
): ScheduleAccess {
  return {
    id: `${activityId}-${week}`,
    activity_id: activityId,
    access_seq: 1,
    week,
    eclo: false,
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

describe("coShareMemberships", () => {
  const location = "PLAT:ALP:H01:EB";

  it("carries each member's own contract-local night", () => {
    const access = [accessRow("A1", 1, 2), accessRow("A2", 1, 5)];
    const occupancy = [
      occupancyRow("A1", 1, location, "g1"),
      occupancyRow("A2", 1, location, "g1"),
    ];
    const memberships = coShareMemberships(occupancy, access, "A1", 1);
    assert.equal(memberships.length, 1);
    assert.deepEqual(memberships[0].members, [
      { activityId: "A1", night: 2 },
      { activityId: "A2", night: 5 },
    ]);
  });

  it("prefers the physical slot for a member's own night", () => {
    const access = [accessRow("A1", 1, 2, 7), accessRow("A2", 1, 5, 8)];
    const occupancy = [
      occupancyRow("A1", 1, location, "g1"),
      occupancyRow("A2", 1, location, "g1"),
    ];
    const memberships = coShareMemberships(occupancy, access, "A1", 1);
    assert.deepEqual(
      memberships[0].members.map((member) => member.night),
      [7, 8],
    );
  });

  it("leaves a member night null when no access row exists", () => {
    const access = [accessRow("A1", 1, 2)];
    const occupancy = [
      occupancyRow("A1", 1, location, "g1"),
      occupancyRow("A2", 1, location, "g1"),
    ];
    const memberships = coShareMemberships(occupancy, access, "A1", 1);
    assert.deepEqual(memberships[0].members, [
      { activityId: "A1", night: 2 },
      { activityId: "A2", night: null },
    ]);
  });

  it("navigates with the member's own night, falling back to the group's", () => {
    const access = [accessRow("A1", 1, 2), accessRow("A2", 1, 5)];
    const occupancy = [
      occupancyRow("A1", 1, location, "g1"),
      occupancyRow("A2", 1, location, "g1"),
    ];
    const memberships = coShareMemberships(occupancy, access, "A1", 1);
    const own = memberships[0].members.find(
      (member) => member.activityId === "A2",
    )!;
    assert.deepEqual(selectionForPossession(own, 1, 9), {
      activityId: "A2",
      week: 1,
      night: 5,
    });
    assert.deepEqual(
      selectionForPossession({ activityId: "A3", night: null }, 1, 9),
      { activityId: "A3", week: 1, night: 9 },
    );
  });
});

describe("capacityReadings", () => {
  const scenarioNetwork = network({
    location_capacities: {
      "PLAT:ALP:H01:EB": 1,
      "PLAT:ALP:H02:EB": 2,
      "PLAT:ALP:H03:EB": 2,
    },
  });

  const occupancy = [
    { id: "1", activity_id: "A1", week: 1, location_id: "PLAT:ALP:H01:EB", co_share_group: "g1" },
    { id: "2", activity_id: "A2", week: 1, location_id: "PLAT:ALP:H01:EB", co_share_group: "g2" },
    { id: "3", activity_id: "A1", week: 1, location_id: "PLAT:ALP:H02:EB", co_share_group: "g1" },
    { id: "4", activity_id: "A3", week: 2, location_id: "PLAT:ALP:H03:EB", co_share_group: "g3" },
    { id: "5", activity_id: "A4", week: 2, location_id: "PLAT:ALP:H03:EB", co_share_group: "g3" },
  ];

  it("counts distinct co-share groups per location-week", () => {
    const readings = capacityReadings(scenarioNetwork, occupancy, "A");
    const h01 = readings.find(
      (reading) =>
        reading.locationId === "PLAT:ALP:H01:EB" && reading.week === 1,
    );
    assert.equal(h01?.used, 2);
    assert.equal(h01?.capacity, 1);
    assert.equal(h01?.excess, 1);
    assert.equal(isAtCapacity(h01!), false);
  });

  it("does not flag a location-week that still has headroom", () => {
    const readings = capacityReadings(scenarioNetwork, occupancy, "A");
    const atCapacity = readings.filter(isAtCapacity);
    const h03 = readings.find(
      (reading) =>
        reading.locationId === "PLAT:ALP:H03:EB" && reading.week === 2,
    );
    assert.equal(h03?.used, 1);
    assert.equal(h03?.capacity, 2);
    assert.equal(isAtCapacity(h03!), false);

    const h02 = readings.find(
      (reading) =>
        reading.locationId === "PLAT:ALP:H02:EB" && reading.week === 1,
    );
    assert.equal(h02?.used, 1);
    assert.equal(isAtCapacity(h02!), false);
    assert.deepEqual(atCapacity, []);
  });

  it("flags a location-week with used equal to a non-zero supply", () => {
    const readings = capacityReadings(
      scenarioNetwork,
      [
        { id: "1", activity_id: "A1", week: 1, location_id: "PLAT:ALP:H03:EB", co_share_group: "g1" },
        { id: "2", activity_id: "A2", week: 1, location_id: "PLAT:ALP:H03:EB", co_share_group: "g2" },
      ],
      "A",
    );
    const h03 = readings.find(
      (reading) => reading.locationId === "PLAT:ALP:H03:EB",
    );
    assert.equal(h03?.used, 2);
    assert.equal(h03?.capacity, 2);
    assert.equal(h03?.excess, 0);
    assert.equal(isAtCapacity(h03!), true);
    assert.deepEqual(readings.filter(isAtCapacity), [h03]);
  });
});
