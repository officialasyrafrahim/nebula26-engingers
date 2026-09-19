import { expect, type Page, type Route } from "@playwright/test";

// AT-15 drives the whole control board against route-mocked API responses so
// the browser suite never needs the real solver, database or worker. The
// payloads mirror backend/app/domain/schemas.py and the nested validator report.

export const RUN_ID = "0f6b1a2c-1111-4a11-8b11-111111111111";
export const JOB_ID = "1a2b3c4d-2222-4b22-9c22-222222222222";

export const INSTANCE_FILE_NAMES = [
  "01_LINES.csv",
  "02_STATIONS.csv",
  "03_SECTORS.csv",
  "04_LOCATION_SUPPLY.csv",
  "05_BUFFER_LOCATION.csv",
  "06_PARAMETERS.csv",
  "07_PROJECT_DETAILS.csv",
  "08_ACTIVITY_DETAILS.csv",
] as const;

// ------------------------------------------------------------------ fixtures

export const planningRun = {
  id: RUN_ID,
  name: "Held-out instance 07",
  parse_status: "OK",
  parse_summary: {
    files: [...INSTANCE_FILE_NAMES],
    counts: {
      lines: 1,
      stations: 2,
      sectors: 1,
      locations: 6,
      contracts: 1,
      activities: 2,
    },
    horizon_start: "2027-01-04",
    horizon_weeks: 4,
    issues: [],
  },
  horizon_start: "2027-01-04",
  horizon_weeks: 4,
  created_at: "2026-09-19T10:00:00Z",
};

// A deliberately unmapped line code. It keeps the DataMall advisory panel in
// its explicit "no mapping" state, so the suite never reaches out to LTA.
export const network = {
  parameters: { horizon_start: "2027-01-04", horizon_weeks: 4 },
  lines: [{ line_code: "HID", line_name: "Held-out Line" }],
  stations: [
    { station_id: "S01", line_code: "HID", seq: 1, is_interchange: false },
    { station_id: "S02", line_code: "HID", seq: 2, is_interchange: false },
  ],
  sectors: [
    {
      sector_id: "SEC:HID:S01_S02",
      line_code: "HID",
      from_station_id: "S01",
      to_station_id: "S02",
      seq: 1,
      is_shared: false,
    },
  ],
  locations: [
    {
      location_id: "PLAT:HID:S01:EB",
      location_kind: "platform",
      line_code: "HID",
      bound: "EB",
      supply_capacity: 2,
    },
    {
      location_id: "PLAT:HID:S02:EB",
      location_kind: "platform",
      line_code: "HID",
      bound: "EB",
      supply_capacity: 2,
    },
    {
      location_id: "SEC:HID:S01_S02:EB",
      location_kind: "tunnel sector",
      line_code: "HID",
      bound: "EB",
      supply_capacity: 2,
    },
    {
      location_id: "PLAT:HID:S01:WB",
      location_kind: "platform",
      line_code: "HID",
      bound: "WB",
      supply_capacity: 2,
    },
    {
      location_id: "PLAT:HID:S02:WB",
      location_kind: "platform",
      line_code: "HID",
      bound: "WB",
      supply_capacity: 2,
    },
    {
      location_id: "SEC:HID:S01_S02:WB",
      location_kind: "tunnel sector",
      line_code: "HID",
      bound: "WB",
      supply_capacity: 2,
    },
  ],
  buffer_rules: [
    {
      nature_of_works: "Non-live (Others)",
      up_to_buffer_sectors: 0,
      opposite_bound_required: false,
    },
  ],
  contracts: [
    {
      contract_number: "HC1",
      contract_description: "Held-out renewal",
      contract_award_date: "2026-01-01",
      activity_type: "Renewal",
      nature_of_activity: "Non-live (Others)",
      contract_priority: 2,
      contract_completion_date: "2027-03-01",
      planned_completion_date: "2027-03-01",
      number_of_workfronts: 1,
      access_type: "C",
      number_of_maximum_access_per_week: 3,
    },
  ],
  activities: [
    {
      activity_id: "HA1",
      contract_number: "HC1",
      activity_type: "Renewal",
      start_location_id: "SEC:HID:S01_S02:EB",
      end_location_id: "SEC:HID:S01_S02:EB",
      total_accesses: 2,
      planned_start_date: "2027-01-04",
      predecessor_activity_id: null,
      activity_priority: 1,
    },
    {
      activity_id: "HA2",
      contract_number: "HC1",
      activity_type: "Renewal",
      start_location_id: "SEC:HID:S01_S02:EB",
      end_location_id: "SEC:HID:S01_S02:EB",
      total_accesses: 1,
      planned_start_date: "2027-01-11",
      predecessor_activity_id: "HA1",
      activity_priority: 2,
    },
  ],
  routes: {
    HA1: ["PLAT:HID:S01:EB", "SEC:HID:S01_S02:EB", "PLAT:HID:S02:EB"],
    HA2: ["PLAT:HID:S01:EB", "SEC:HID:S01_S02:EB", "PLAT:HID:S02:EB"],
  },
  location_capacities: {
    "PLAT:HID:S01:EB": 2,
    "PLAT:HID:S02:EB": 2,
    "SEC:HID:S01_S02:EB": 2,
    "PLAT:HID:S01:WB": 2,
    "PLAT:HID:S02:WB": 2,
    "SEC:HID:S01_S02:WB": 2,
  },
  activity_spans: {
    HA1: {
      occupied_locations: ["SEC:HID:S01_S02:EB"],
      closure_locations: ["SEC:HID:S01_S02:EB"],
      mirrored_locations: [],
      interchange_locations: [],
    },
    HA2: {
      occupied_locations: ["SEC:HID:S01_S02:EB"],
      closure_locations: ["SEC:HID:S01_S02:EB"],
      mirrored_locations: [],
      interchange_locations: [],
    },
  },
};

export const schedule = {
  run_id: RUN_ID,
  job_id: JOB_ID,
  scenario: "A",
  access: [
    {
      id: "acc-1",
      activity_id: "HA1",
      access_seq: 1,
      week: 1,
      eclo: false,
      access_night: 1,
      physical_night: 1,
    },
    {
      id: "acc-2",
      activity_id: "HA1",
      access_seq: 2,
      week: 2,
      eclo: false,
      access_night: 1,
      physical_night: 1,
    },
    {
      id: "acc-3",
      activity_id: "HA2",
      access_seq: 1,
      week: 3,
      eclo: false,
      access_night: 1,
      physical_night: 1,
    },
  ],
  occupancy: [
    {
      id: "occ-1",
      activity_id: "HA1",
      week: 1,
      location_id: "SEC:HID:S01_S02:EB",
      co_share_group: "b1",
    },
    {
      id: "occ-2",
      activity_id: "HA1",
      week: 2,
      location_id: "SEC:HID:S01_S02:EB",
      co_share_group: "b1",
    },
    {
      id: "occ-3",
      activity_id: "HA2",
      week: 3,
      location_id: "SEC:HID:S01_S02:EB",
      co_share_group: "b1",
    },
  ],
  results: [
    {
      id: "res-1",
      contract_number: "HC1",
      simulated_completion_date: "2027-01-25",
      overrun_days: 0,
    },
  ],
  explanations: [
    {
      activity_id: "HA1",
      reason_codes: ["PLANNED_START"],
      summary: "HA1 starts on its planned start week with no displacement.",
      evidence: { week: 1 },
    },
    {
      activity_id: "HA2",
      reason_codes: ["PREDECESSOR_ORDER"],
      summary: "HA2 follows its predecessor without early access.",
      evidence: { week: 3 },
    },
  ],
  physical_checks: {
    passed: true,
    checks: [
      {
        name: "physical_slot_universe",
        passed: true,
        detail: "Every access placement maps to a physical slot.",
      },
    ],
  },
};

export const validatorReportRead = {
  id: "report-1",
  job_id: JOB_ID,
  scenario: "A",
  feasible: true,
  workload_complete: true,
  ready_for_submission: true,
  authority: "fallback",
  created_at: "2026-09-19T10:05:00Z",
  report: {
    scenario: "A",
    feasible: true,
    workload_complete: true,
    ready_for_submission: true,
    authority: "fallback",
    validator_source: "fallback",
    hard_violations: [],
    soft_scores: {
      scenario: "A",
      overrun_days_total: 0,
      contracts_overrunning: 0,
      earliness_days_total: 1,
      excess_access_nights_total: 0,
      eclo_nights_total: 0,
      priority_overrun: { "2": 0 },
      priority_weighted_score: 0,
      objective_score: 0,
      formula_version: "fallback-v1",
    },
    detail: { capacity_hotspots: [], nights_scheduled: 3, eclo_nights: 0 },
    parse_errors: [],
  },
};

// AT-12-style variant: the gate withholds export on a hard violation.
export const blockedValidatorReportRead = {
  ...validatorReportRead,
  id: "report-blocked",
  feasible: false,
  workload_complete: false,
  ready_for_submission: false,
  report: {
    ...validatorReportRead.report,
    feasible: false,
    workload_complete: false,
    ready_for_submission: false,
    hard_violations: [
      {
        rule: "workload_complete",
        severity: "hard",
        detail: "Activity HA2 is not fully scheduled.",
      },
    ],
  },
};

const queuedJob = {
  id: JOB_ID,
  run_id: RUN_ID,
  scenario: "A",
  state: "QUEUED",
  request: { scenario: "A" },
  result: null,
  error: null,
  cancel_requested: false,
  time_limit_seconds: null,
  seed: null,
  submitted_at: "2026-09-19T10:04:00Z",
  started_at: null,
  finished_at: null,
  created_at: "2026-09-19T10:04:00Z",
};

const completedJob = {
  ...queuedJob,
  state: "COMPLETED",
  result: {
    access_count: 3,
    occupancy_count: 3,
    contract_count: 1,
    horizon_weeks_used: 3,
  },
  started_at: "2026-09-19T10:04:01Z",
  finished_at: "2026-09-19T10:05:00Z",
};

// ------------------------------------------------------------------ mocking

export interface MockState {
  jobPolls: number;
  exportRequests: number;
}

export interface MockOptions {
  // Set to a non-200 status to keep the network locked and the Optimise,
  // Validate, Explain and Export tabs unavailable.
  networkStatus?: number;
  // Replace the served validator report, for example to force a blocked gate.
  report?: Record<string, unknown>;
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export async function installApiMocks(
  page: Page,
  options: MockOptions = {},
): Promise<MockState> {
  const state: MockState = { jobPolls: 0, exportRequests: 0 };
  const networkStatus = options.networkStatus ?? 200;

  await page.route("**/healthz", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    }),
  );

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;

    if (method === "GET" && path === "/api/v1/runs") {
      return fulfillJson(route, []);
    }
    if (method === "POST" && path === "/api/v1/runs") {
      return fulfillJson(route, planningRun, 201);
    }
    if (method === "GET" && path === `/api/v1/runs/${RUN_ID}/network`) {
      if (networkStatus !== 200) {
        return fulfillJson(route, { detail: "network unavailable" }, networkStatus);
      }
      return fulfillJson(route, network);
    }
    if (method === "GET" && path === `/api/v1/runs/${RUN_ID}/jobs`) {
      return fulfillJson(route, []);
    }
    if (method === "POST" && path === `/api/v1/runs/${RUN_ID}/jobs`) {
      return fulfillJson(route, queuedJob, 202);
    }
    if (method === "GET" && path === `/api/v1/runs/${RUN_ID}/jobs/${JOB_ID}`) {
      state.jobPolls += 1;
      return fulfillJson(route, completedJob);
    }
    if (
      method === "GET" &&
      path === `/api/v1/runs/${RUN_ID}/jobs/${JOB_ID}/schedule`
    ) {
      return fulfillJson(route, schedule);
    }
    if (
      method === "GET" &&
      path === `/api/v1/runs/${RUN_ID}/jobs/${JOB_ID}/report`
    ) {
      return fulfillJson(route, options.report ?? validatorReportRead);
    }
    if (
      method === "GET" &&
      path === `/api/v1/runs/${RUN_ID}/jobs/${JOB_ID}/export`
    ) {
      state.exportRequests += 1;
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="scenario-A.zip"',
        },
        body: Buffer.from("PK\x05\x06" + "\x00".repeat(18), "binary"),
      });
      return;
    }
    return fulfillJson(
      route,
      { detail: `Unmocked request: ${method} ${path}` },
      501,
    );
  });

  return state;
}

// ------------------------------------------------------------------ driving

export async function uploadHiddenInstance(page: Page) {
  const files = INSTANCE_FILE_NAMES.map((name) => ({
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(`fixture placeholder for ${name}\n`),
  }));
  await page.locator("#instance-files").setInputFiles(files);
  await expect(
    page.getByText("All eight files staged. Ready to compile."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Compile planning run" }).click();
}

export async function dispatchScenarioA(page: Page) {
  await page.getByRole("tab", { name: /Optimise/ }).click();
  await expect(page.getByRole("heading", { name: "Scenario dispatch" })).toBeVisible();
  await page.getByRole("button", { name: /Dispatch A/ }).click();
}

// Upload, inspect, dispatch and wait for the validator stage. The job poll is
// mocked to complete immediately, so the whole hidden-instance flow runs
// without a solver.
export async function driveToValidatedResult(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Instance intake" }),
  ).toBeVisible();
  await uploadHiddenInstance(page);

  await expect(page.locator("#workflow-panel-inspect")).toBeFocused();
  await expect(page.getByText("parsed topology")).toBeVisible();

  await dispatchScenarioA(page);

  await expect(page.locator("#workflow-panel-validate")).toBeVisible();
  await expect(page.locator("#workflow-panel-validate")).toBeFocused();
  await expect(
    page.getByRole("heading", { name: "Validation assurance" }),
  ).toBeVisible();
}

export async function exportScenarioA(page: Page) {
  await page.getByRole("tab", { name: /Export/ }).click();
  await expect(
    page.getByRole("heading", { name: "Submission export" }),
  ).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download .*zip/ }).click();
  return downloadPromise;
}

export async function horizontalOverflowPx(page: Page): Promise<number> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    return Math.max(
      root.scrollWidth - root.clientWidth,
      body.scrollWidth - root.clientWidth,
      0,
    );
  });
}
