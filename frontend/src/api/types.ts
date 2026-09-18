// Typed contracts mirroring backend/app/domain/schemas.py and the nested
// validator report in backend/app/modules/validator/report.py.

export type Scenario = "A" | "B" | "C";

export type JobState =
  | "QUEUED"
  | "RUNNING"
  | "VALIDATING"
  | "COMPLETED"
  | "INFEASIBLE"
  | "FAILED"
  | "TIMED_OUT"
  | "CANCELLED";

export const ACTIVE_JOB_STATES: readonly JobState[] = [
  "QUEUED",
  "RUNNING",
  "VALIDATING",
];

export const TERMINAL_JOB_STATES: readonly JobState[] = [
  "COMPLETED",
  "INFEASIBLE",
  "FAILED",
  "TIMED_OUT",
  "CANCELLED",
];

export function isActiveJob(state: JobState): boolean {
  return ACTIVE_JOB_STATES.includes(state);
}

export function isTerminalJob(state: JobState): boolean {
  return TERMINAL_JOB_STATES.includes(state);
}

export interface ParseSummary {
  files: string[];
  counts: Record<string, number>;
  horizon_start: string | null;
  horizon_weeks: number | null;
  issues: string[];
}

export interface PlanningRun {
  id: string;
  name: string | null;
  parse_status: string;
  parse_summary: ParseSummary;
  horizon_start: string | null;
  horizon_weeks: number | null;
  created_at: string;
}

export interface ScenarioJob {
  id: string;
  run_id: string;
  scenario: Scenario;
  state: JobState;
  request: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  cancel_requested: boolean;
  time_limit_seconds: number | null;
  seed: number | null;
  submitted_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ScenarioJobCreate {
  scenario: Scenario;
  time_limit_seconds?: number;
  seed?: number;
}

export interface Line {
  line_code: string;
  line_name: string;
}

export interface Station {
  station_id: string;
  line_code: string;
  seq: number;
  is_interchange: boolean;
}

export interface Sector {
  sector_id: string;
  line_code: string;
  from_station_id: string;
  to_station_id: string;
  seq: number;
  is_shared: boolean;
}

export interface LocationSupply {
  location_id: string;
  location_kind: string;
  line_code: string;
  bound: string;
  supply_capacity: number;
}

export interface BufferRule {
  nature_of_works: string;
  up_to_buffer_sectors: number;
  opposite_bound_required: boolean;
}

export interface Contract {
  contract_number: string;
  contract_description: string;
  contract_award_date: string;
  activity_type: string;
  nature_of_activity: string;
  contract_priority: number;
  contract_completion_date: string;
  planned_completion_date: string;
  number_of_workfronts: number;
  access_type: string;
  number_of_maximum_access_per_week: number;
}

export interface Activity {
  activity_id: string;
  contract_number: string;
  activity_type: string;
  start_location_id: string;
  end_location_id: string;
  total_accesses: number;
  planned_start_date: string;
  predecessor_activity_id: string | null;
  activity_priority: number;
}

export interface NetworkResponse {
  parameters: Record<string, unknown>;
  lines: Line[];
  stations: Station[];
  sectors: Sector[];
  locations: LocationSupply[];
  buffer_rules: BufferRule[];
  contracts: Contract[];
  activities: Activity[];
  routes: Record<string, string[]>;
  location_capacities: Record<string, number>;
}

export interface ScheduleAccess {
  id: string;
  activity_id: string;
  access_seq: number;
  week: number;
  eclo: boolean;
  access_night: number;
}

export interface ScheduleOccupancy {
  id: string;
  activity_id: string;
  week: number;
  location_id: string;
  co_share_group: string;
}

export interface ContractResult {
  id: string;
  contract_number: string;
  simulated_completion_date: string;
  overrun_days: number;
}

export interface ScheduleResponse {
  run_id: string;
  job_id: string;
  scenario: Scenario;
  access: ScheduleAccess[];
  occupancy: ScheduleOccupancy[];
  results: ContractResult[];
}

export type Authority = "official" | "fallback";

export interface HardViolation {
  rule: string;
  severity: "hard";
  detail: string;
}

export interface SoftScores {
  scenario: string;
  overrun_days_total: number;
  contracts_overrunning: number;
  earliness_days_total: number;
  excess_access_nights_total: number;
  eclo_nights_total: number;
  priority_overrun: Record<string, number>;
  priority_weighted_score: number;
  objective_score: number | null;
  formula_version: string | null;
}

export interface CapacityHotspot {
  location_id: string;
  week: number;
  used: number;
  capacity: number;
  excess: number;
}

export interface ValidatorDetail {
  capacity_hotspots: CapacityHotspot[];
  nights_scheduled: number;
  eclo_nights: number;
}

export interface ValidatorReport {
  scenario: string;
  feasible: boolean;
  workload_complete: boolean;
  ready_for_submission: boolean;
  authority: Authority;
  validator_source: Authority;
  hard_violations: HardViolation[];
  soft_scores: SoftScores;
  detail: ValidatorDetail;
  parse_errors: string[];
}

export interface ValidatorReportRead {
  id: string;
  job_id: string;
  scenario: string;
  feasible: boolean;
  workload_complete: boolean;
  ready_for_submission: boolean;
  authority: string;
  report: ValidatorReport;
  created_at: string;
}

export type HealthStatus = Record<string, unknown>;
