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

export interface ActivitySpan {
  occupied_locations: string[];
  closure_locations: string[];
  mirrored_locations: string[];
  interchange_locations: string[];
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
  activity_spans?: Record<string, ActivitySpan> | null;
}

export interface ScheduleAccess {
  id: string;
  activity_id: string;
  access_seq: number;
  week: number;
  eclo: boolean;
  access_night: number;
  physical_night?: number | null;
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

export interface ScheduleExplanation {
  activity_id: string;
  reason_codes: string[];
  summary: string;
  evidence: Record<string, unknown>;
}

export interface PhysicalCheckItem {
  name: string;
  passed: boolean;
  detail: string | Record<string, unknown>;
}

export interface PhysicalCheckReport {
  passed: boolean;
  checks: PhysicalCheckItem[];
}

export interface ScheduleResponse {
  run_id: string;
  job_id: string;
  scenario: Scenario;
  access: ScheduleAccess[];
  occupancy: ScheduleOccupancy[];
  results: ContractResult[];
  explanations: ScheduleExplanation[];
  physical_checks?: PhysicalCheckReport | null;
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

// ------------------------------------------------------------- replanning
// Mirrors backend/app/domain/schemas.py. A disruption is a discriminated union
// on `kind`. A replan records the impact assessment, the before/after diff and
// the minimal-churn outcome of one disrupted solve. The source job's published
// CSVs are never touched.

export type DisruptionKind =
  | "supply_drop"
  | "location_unavailable"
  | "night_unavailable"
  | "urgent_activity";

export interface SupplyDropDisruption {
  kind: "supply_drop";
  location_id: string;
  new_supply: number;
}

export interface LocationUnavailableDisruption {
  kind: "location_unavailable";
  location_id: string;
  weeks: number[] | null;
}

export interface NightUnavailableDisruption {
  kind: "night_unavailable";
  physical_night: number;
  weeks: number[] | null;
}

export interface UrgentActivityDisruption {
  kind: "urgent_activity";
  activity_id: string;
  contract_number: string;
  activity_type?: string | null;
  start_location_id: string;
  end_location_id: string;
  total_accesses: number;
  planned_start_date: string;
  predecessor_activity_id?: string | null;
  activity_priority: number;
}

export type Disruption =
  | SupplyDropDisruption
  | LocationUnavailableDisruption
  | NightUnavailableDisruption
  | UrgentActivityDisruption;

export interface ReplanRequest {
  disruptions: Disruption[];
  time_limit_seconds?: number;
  seed?: number;
  horizon_extension_weeks?: number;
}

export interface ReplanInvalidPlacement {
  activity_id: string;
  week: number;
  physical_night: number | null;
  location_id: string | null;
  reason: string;
}

export interface ReplanAffectedLocationWeek {
  location_id: string;
  week: number;
  used: number;
  capacity: number;
  excess: number;
  reason: string;
}

export interface ReplanWorkload {
  access_nights_before: number;
  invalid_access_nights: number;
  injected_access_nights: number;
  access_nights_after_lower_bound: number;
}

export interface ReplanOverrunImpact {
  overrun_days_before: number;
  contracts_overrunning_before: number;
  displaced_access_nights: number;
  worst_case_additional_overrun_days: number;
  worst_case_overrun_days: number;
}

export interface ReplanImpact {
  invalid_placements: ReplanInvalidPlacement[];
  affected_activities: string[];
  affected_contracts: string[];
  affected_location_weeks: ReplanAffectedLocationWeek[];
  workload: ReplanWorkload;
  overrun: ReplanOverrunImpact;
  notes: string[];
}

export type SlotPair = [number, number | null];

export interface ReplanMovedPlacement {
  activity_id: string;
  from: SlotPair[];
  to: SlotPair[];
}

export interface ReplanDiffTotals {
  original_accesses: number;
  replan_accesses: number;
  reused_accesses: number;
  moved_accesses: number;
  moved_activities: number;
  unchanged_activities: number;
}

export interface ReplanDiff {
  moved: ReplanMovedPlacement[];
  unchanged: string[];
  added: string[];
  removed: string[];
  newly_unsatisfiable: string[];
  totals: ReplanDiffTotals;
}

export interface ReplanChurn {
  moved_accesses: number;
  access_weight: number;
}

export interface ReplanResultPayload {
  feasible: boolean;
  status: string;
  horizon_weeks_used: number;
  infeasibility_reasons: string[];
  objective_breakdown: Record<string, unknown>;
  binding_reasons: Record<string, string[]>;
  churn: ReplanChurn;
  access?: ScheduleAccess[];
  occupancy?: ScheduleOccupancy[];
  contract_results?: unknown[];
  contract_completion?: Record<string, string>;
  physical_checks?: PhysicalCheckReport | null;
}

export interface ReplanRead {
  id: string;
  run_id: string;
  job_id: string;
  scenario: Scenario;
  status: string;
  safe: boolean;
  seed: number | null;
  churn_cost: number;
  disruption: Disruption[];
  impact: ReplanImpact;
  diff: ReplanDiff;
  result: ReplanResultPayload | null;
  error: string | null;
  created_at: string;
}

export type HealthStatus = Record<string, unknown>;

// --------------------------------------------------------- LTA DataMall context
// Advisory-only contracts mirroring backend/app/modules/datamall/schemas.py.
// The DataMall account key is never part of any payload.

export type DatamallState = "ok" | "empty" | "unconfigured" | "error";

export interface DatamallSourceStatus {
  dataset: string;
  source: string;
  source_url: string;
  interval: string;
  state: DatamallState;
  available: boolean;
  configured: boolean;
  retrieved_at: string | null;
  cached: boolean;
  http_status: number | null;
  reason: string | null;
}

export interface DatamallAdvisory {
  advisory: boolean;
  label: string;
  disclaimer: string;
  measurement_note: string;
}

export interface PassengerVolumeRecord {
  station_code: string;
  station_name: string | null;
  solver_line: string | null;
  solver_station: string | null;
  datamall_line: string | null;
  tap_in_weekday: number | null;
  tap_out_weekday: number | null;
  tap_in_weekend: number | null;
  tap_out_weekend: number | null;
  total_weekday: number | null;
  total_weekend: number | null;
}

export interface OdVolumeRecord {
  origin_code: string;
  origin_name: string | null;
  destination_code: string;
  destination_name: string | null;
  weekday_trips: number;
  weekend_trips: number;
}

export interface CrowdDensityRecord {
  station_code: string;
  station_name: string | null;
  solver_line: string | null;
  solver_station: string | null;
  datamall_line: string | null;
  crowd_level: string;
  interval_start: string | null;
  interval_end: string | null;
}

export interface TrainAlertRecord {
  line: string | null;
  direction: string | null;
  stations: string[];
  free_public_bus: string[];
  free_mrt_shuttle: string[];
  message: string | null;
  created_at: string | null;
}

export interface MappingStationRead {
  solver_line: string;
  solver_station: string;
  name: string;
  code: string;
  datamall_line: string;
}

export interface MappingNetworkRead {
  key: string;
  label: string;
  solver_lines: string[];
  crowd_lines: string[];
  alert_lines: string[];
  stations: MappingStationRead[];
}

export interface DatamallNetworkContext {
  network: string;
  supported: boolean;
  advisory: DatamallAdvisory;
  generated_at: string;
  mapping: MappingNetworkRead | null;
  reason: string | null;
  sources: DatamallSourceStatus[];
  passenger_volume: PassengerVolumeRecord[];
  od_volume: OdVolumeRecord[];
  crowd_density: CrowdDensityRecord[];
  crowd_forecast: CrowdDensityRecord[];
  alerts: TrainAlertRecord[];
  alerts_status: number | null;
}

export interface DatamallStatusResponse {
  configured: boolean;
  enabled: boolean;
  state: DatamallState;
  reason: string | null;
  datasets: DatamallSourceStatus[];
}
