import type { ScheduleExplanation } from "../api/types";
import type { ActivitySelection } from "../lib/schematic";
import Panel from "./Panel";

interface ExplanationsPanelProps {
  explanations: ScheduleExplanation[];
  selectedActivityId?: string | null;
  onSelect?: (selection: ActivitySelection) => void;
}

const REASON_LABELS: Record<string, string> = {
  PLANNED_START: "Planned start",
  PREDECESSOR: "Predecessor",
  BUFFER_CLOSURE: "Buffer / closure",
  LIVE_MIRROR: "Live mirror",
  INTERCHANGE: "Interchange",
  CAPACITY: "Capacity",
  WEEKLY_CAP: "Weekly cap",
  WORKFRONT: "Workfront",
  POSSESSION_MIX: "Possession mix",
  CO_SHARE_PACKED: "Co-share packed",
  ECLO_WINDOW: "ECLO window",
  PRIORITY_OVERRUN: "Priority overrun",
  HORIZON_EXTENDED: "Horizon extended",
};

const EVIDENCE_LABELS: Record<string, string> = {
  first_week: "First week",
  planned_start_week: "Planned start week",
  predecessor_activity_id: "Predecessor",
  predecessor_last_week: "Predecessor last week",
  horizon_weeks: "Horizon weeks",
  horizon_extended: "Horizon extended",
  access_type: "Access type",
  buffer_sectors: "Buffer sectors",
  closure_location_count: "Closure locations",
  opposite_bound_required: "Opposite bound",
  mirrored_location_count: "Mirrored locations",
  interchange_location_count: "Interchange locations",
  mix_groups: "Possession groups",
  co_share_group: "Co-share group",
  co_share_partners: "Co-share partners",
  co_share_size: "Co-share size",
  capacity_location: "Capacity location",
  capacity_week: "Capacity week",
  capacity_used: "Capacity used",
  capacity_limit: "Capacity limit",
};

// Evidence keys each displacement reason code must justify. When a code is
// present but none of its keys are, the panel says so instead of implying a
// cause the server did not record. Codes without an entry need no extra facts.
const REASON_EVIDENCE_KEYS: Record<string, string[]> = {
  BUFFER_CLOSURE: ["buffer_sectors", "closure_location_count"],
  LIVE_MIRROR: ["opposite_bound_required", "mirrored_location_count"],
  INTERCHANGE: ["interchange_location_count"],
  POSSESSION_MIX: ["access_type", "mix_groups"],
  CO_SHARE_PACKED: ["co_share_group", "co_share_partners"],
  CAPACITY: ["capacity_location", "capacity_limit"],
};

function formatEvidenceValue(value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) {
    return value.map((item) => formatEvidenceValue(item)).join(", ");
  }
  if (typeof value === "object") return JSON.stringify(value) ?? "—";
  return String(value);
}

// Deterministic explanation panel. Entries are ordered by activity id and the
// evidence keys are ordered alphabetically so a reload cannot reshuffle the
// panel. No scheduling logic runs here; the server owns the explanation.
export default function ExplanationsPanel({
  explanations,
  selectedActivityId = null,
  onSelect,
}: ExplanationsPanelProps) {
  const ordered = [...explanations].sort((left, right) =>
    left.activity_id.localeCompare(right.activity_id),
  );

  return (
    <Panel
      title="Activity explanations"
      eyebrow="Stage 5 · Explain · deterministic evidence"
      actions={
        <span className="panel__meter">
          {ordered.length} {ordered.length === 1 ? "activity" : "activities"} explained
        </span>
      }
    >
      {ordered.length === 0 ? (
        <p className="empty">No activity explanations for this schedule.</p>
      ) : (
        <ul className="explanations" aria-label="Activity explanations">
          {ordered.map((entry) => {
            const reasonCodes = entry.reason_codes ?? [];
            const evidenceMap = entry.evidence ?? {};
            const evidence = Object.entries(evidenceMap).sort(
              ([left], [right]) => left.localeCompare(right),
            );
            const unsupported = reasonCodes.filter((code) => {
              const keys = REASON_EVIDENCE_KEYS[code];
              if (!keys) return false;
              return !keys.some((key) => evidenceMap[key] != null);
            });
            return (
              <li
                key={entry.activity_id}
                className={`explanations__item${
                  selectedActivityId === entry.activity_id
                    ? " explanations__item--selected"
                    : ""
                }`}
              >
                <div className="explanations__head">
                  {onSelect ? (
                    <button
                      type="button"
                      className="explanations__id"
                      onClick={() =>
                        onSelect({
                          activityId: entry.activity_id,
                          week: null,
                          night: null,
                        })
                      }
                      title={`Select ${entry.activity_id} across the board`}
                    >
                      {entry.activity_id}
                    </button>
                  ) : (
                    <code className="explanations__id">{entry.activity_id}</code>
                  )}
                  <p className="explanations__summary">{entry.summary}</p>
                </div>
                {reasonCodes.length > 0 ? (
                  <ul
                    className="reasons"
                    aria-label={`Reason codes for ${entry.activity_id}`}
                  >
                    {reasonCodes.map((code) => (
                      <li key={code} className="reason">
                        <code>{code}</code>
                        <span>{REASON_LABELS[code] ?? code}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {unsupported.length > 0 ? (
                  <p className="explanations__unsupported">
                    No supporting evidence recorded for {unsupported.join(", ")}. The
                    solver reported the cause without local facts.
                  </p>
                ) : null}
                {evidence.length > 0 ? (
                  <dl className="explanations__evidence">
                    {evidence.map(([key, value]) => (
                      <div key={key} className="explanations__fact">
                        <dt>{EVIDENCE_LABELS[key] ?? key}</dt>
                        <dd>{formatEvidenceValue(value)}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
