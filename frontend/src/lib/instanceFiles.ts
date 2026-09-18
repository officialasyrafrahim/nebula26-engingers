// The exact eight published instance files, in the canonical upload order.

export interface InstanceFileSpec {
  name: string;
  label: string;
  columns: string;
}

export const INSTANCE_FILES: readonly InstanceFileSpec[] = [
  {
    name: "01_LINES.csv",
    label: "Lines",
    columns: "line_code, line_name",
  },
  {
    name: "02_STATIONS.csv",
    label: "Stations",
    columns: "station_id, line_code, seq, is_interchange",
  },
  {
    name: "03_SECTORS.csv",
    label: "Sectors",
    columns: "sector_id, line_code, from_station_id, to_station_id, seq, is_shared",
  },
  {
    name: "04_LOCATION_SUPPLY.csv",
    label: "Location supply",
    columns: "location_id, location_kind, line_code, bound, supply_capacity",
  },
  {
    name: "05_BUFFER_LOCATION.csv",
    label: "Buffer rules",
    columns: "nature_of_works, up_to_buffer_sectors, opposite_bound_required",
  },
  {
    name: "06_PARAMETERS.csv",
    label: "Parameters",
    columns: "key, value",
  },
  {
    name: "07_PROJECT_DETAILS.csv",
    label: "Project details",
    columns:
      "contract_number, contract_description, contract_award_date, activity_type, " +
      "nature_of_activity, contract_priority, contract_completion_date, " +
      "planned_completion_date, number_of_workfronts, access_type, " +
      "number_of_maximum_access_per_week",
  },
  {
    name: "08_ACTIVITY_DETAILS.csv",
    label: "Activity details",
    columns:
      "activity_id, contract_number, activity_type, start_location_id, " +
      "end_location_id, total_accesses, planned_start_date, " +
      "predecessor_activity_id, activity_priority",
  },
];

export const INSTANCE_FILE_NAMES: readonly string[] = INSTANCE_FILES.map(
  (spec) => spec.name,
);

export function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}
