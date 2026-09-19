import type { ScheduleExplanation } from "../api/types";
import {
  BINDING_LABELS,
  DISPLACEMENT_EVIDENCE_KEYS,
  displacementReading,
  evidenceIsNeutral,
  reasonEvidenceKeys,
  reasonSupport,
} from "../lib/explanations";
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
  possession_conflicts: "Possession conflicts",
};

const DISPLACEMENT_KEY_SET: ReadonlySet<string> = new Set(
  DISPLACEMENT_EVIDENCE_KEYS,
);

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
            const displacement = displacementReading(evidenceMap);
            // Displacement facts get their own truth-checked block below, so the
            // generic list is only the remaining structural evidence.
            const evidence = Object.entries(evidenceMap)
              .filter(([key]) => !DISPLACEMENT_KEY_SET.has(key))
              .sort(([left], [right]) => left.localeCompare(right));
            // A reason is only supported when one of its facts actually
            // confirms it. A false boolean or a zero count is recorded but does
            // not count as proof, so it can never sit under a claimed cause as
            // if it backed it.
            const { unsupported } = reasonSupport(evidenceMap, reasonCodes);
            const reasonKeys = reasonEvidenceKeys(reasonCodes);
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
                    No recorded evidence confirms {unsupported.join(", ")}. The solver
                    reported the cause without supporting facts, so the zero or false
                    values below are shown for completeness only.
                  </p>
                ) : null}

                <div className="explanations__displacement">
                  <p
                    className={
                      displacement.present
                        ? "explanations__displacement-note"
                        : "explanations__displacement-none"
                    }
                  >
                    {displacement.note}
                  </p>
                  {displacement.present && displacement.displaced ? (
                    <>
                      <dl className="explanations__evidence">
                        {displacement.plannedEarliestWeek != null ? (
                          <div className="explanations__fact">
                            <dt>Planned earliest</dt>
                            <dd>W{displacement.plannedEarliestWeek}</dd>
                          </div>
                        ) : null}
                        {displacement.actualFirstWeek != null ? (
                          <div className="explanations__fact">
                            <dt>First access</dt>
                            <dd>W{displacement.actualFirstWeek}</dd>
                          </div>
                        ) : null}
                        {displacement.rejectedWeeks.length > 0 ? (
                          <div className="explanations__fact">
                            <dt>Rejected weeks</dt>
                            <dd>
                              {displacement.rejectedWeeks
                                .map((value) => `W${value}`)
                                .join(", ")}
                            </dd>
                          </div>
                        ) : null}
                        {displacement.bindingWeek != null ? (
                          <div className="explanations__fact">
                            <dt>Binding week</dt>
                            <dd>W{displacement.bindingWeek}</dd>
                          </div>
                        ) : null}
                      </dl>
                      {displacement.supportedConstraints.length > 0 ? (
                        <ul
                          className="reasons"
                          aria-label={`Binding constraints for ${entry.activity_id}`}
                        >
                          {displacement.supportedConstraints.map((code) => (
                            <li key={code} className="reason">
                              <code>{code}</code>
                              <span>{BINDING_LABELS[code] ?? code}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {displacement.unsupportedConstraints.length > 0 ? (
                        <p className="explanations__unsupported">
                          No recorded detail confirms{" "}
                          {displacement.unsupportedConstraints.join(", ")}, so the
                          board does not name{" "}
                          {displacement.unsupportedConstraints.length === 1
                            ? "it"
                            : "them"}{" "}
                          as the cause.
                        </p>
                      ) : null}
                    </>
                  ) : null}
                </div>

                {evidence.length > 0 ? (
                  <dl className="explanations__evidence">
                    {evidence.map(([key, value]) => {
                      const neutral = evidenceIsNeutral(key, value, reasonKeys);
                      return (
                        <div
                          key={key}
                          className={`explanations__fact${
                            neutral ? " explanations__fact--neutral" : ""
                          }`}
                        >
                          <dt>{EVIDENCE_LABELS[key] ?? key}</dt>
                          <dd>
                            {formatEvidenceValue(value)}
                            {neutral ? (
                              <span className="explanations__fact-flag">
                                does not support
                              </span>
                            ) : null}
                          </dd>
                        </div>
                      );
                    })}
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
