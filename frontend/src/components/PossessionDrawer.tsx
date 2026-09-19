import type { ReactNode } from "react";

import type { NetworkResponse, ScheduleResponse } from "../api/types";
import {
  displacementReading,
  BINDING_LABELS,
} from "../lib/explanations";
import {
  accessSummary,
  activityCapacityReadings,
  coShareMemberships,
  effectiveNight,
  nightSourceLabel,
  nightSourceOf,
  selectionForPossession,
  type ActivitySelection,
  type CapacityStatus,
} from "../lib/schematic";
import { formatNumber } from "../lib/format";
import SignalLamp, { type LampTone } from "./SignalLamp";

const BINDING_DETAIL_LABELS: Record<string, string> = {
  week: "Week",
  night: "Night",
  used: "Used",
  limit: "Limit",
  location_id: "Location",
  capacity: "Capacity",
  counterpart_activity_id: "Counterpart activity",
  occupied_by: "Occupied by",
};

interface PossessionDrawerProps {
  selection: ActivitySelection;
  network: NetworkResponse;
  schedule: ScheduleResponse;
  scenario: string;
  onClose: () => void;
  onSelect: (selection: ActivitySelection) => void;
}

const STATUS_LABELS: Record<CapacityStatus, string> = {
  ok: "within supply",
  blocked: "blocked at capacity",
  "excess-soft": "soft excess",
  elastic: "elastic possession",
  hard: "hard over capacity",
};

const STATUS_TONES: Record<CapacityStatus, LampTone> = {
  ok: "ok",
  blocked: "danger",
  "excess-soft": "warn",
  elastic: "info",
  hard: "danger",
};

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="drawer__fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatDetailValue(value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function PossessionDrawer({
  selection,
  network,
  schedule,
  scenario,
  onClose,
  onSelect,
}: PossessionDrawerProps) {
  const activity = network.activities?.find(
    (entry) => entry.activity_id === selection.activityId,
  );
  const contract = network.contracts?.find(
    (entry) => entry.contract_number === activity?.contract_number,
  );
  const summary = accessSummary(schedule.access, selection.activityId);
  const weekRow =
    selection.week != null
      ? summary.rows.find((row) => row.week === selection.week)
      : undefined;
  const selectedNight =
    selection.night ?? (weekRow ? effectiveNight(weekRow) : null);
  const memberships = coShareMemberships(
    schedule.occupancy,
    schedule.access,
    selection.activityId,
    selection.week,
  );
  const readings = activityCapacityReadings(
    network,
    schedule.occupancy,
    scenario,
    selection.activityId,
    selection.week,
  );
  const explanation = schedule.explanations?.find(
    (entry) => entry.activity_id === selection.activityId,
  );
  const displacement = displacementReading(explanation?.evidence ?? {});
  const firstAccess = summary.rows[0] ?? null;
  const firstNight = firstAccess ? effectiveNight(firstAccess) : null;

  const source = nightSourceOf(schedule.access);
  const nightQualifier = selectedNight != null ? ` (${nightSourceLabel(source)})` : "";

  const ecloUsed = summary.eclo > 0;

  return (
    <>
      <div className="drawer-backdrop" aria-hidden="true" onClick={onClose} />
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Possession detail for ${selection.activityId}`}
      >
        <header className="drawer__header">
          <div className="drawer__heading">
            <p className="drawer__eyebrow">Possession detail</p>
            <h2 className="drawer__title">
              <code>{selection.activityId}</code>
            </h2>
            <p className="drawer__subtitle">
              {contract?.contract_description ?? "Unknown contract"}
            </p>
          </div>
          <button type="button" className="btn btn--tiny" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer__body">
          <dl className="drawer__facts">
            <Fact label="Activity" value={selection.activityId} />
            <Fact label="Contract" value={contract?.contract_number ?? "—"} />
            <Fact
              label="Nature"
              value={contract?.nature_of_activity ?? activity?.activity_type ?? "—"}
            />
            <Fact
              label="Access type"
              value={contract?.access_type ?? activity?.activity_type ?? "—"}
            />
            <Fact
              label="Workfront"
              value={
                contract ? `${contract.number_of_workfronts} concurrent` : "—"
              }
            />
            <Fact
              label="Total accesses"
              value={formatNumber(activity?.total_accesses)}
            />
            <Fact
              label="Scheduled accesses"
              value={`${formatNumber(summary.scheduled)} · ${formatNumber(summary.yieldUnits)} units`}
            />
            <Fact
              label="ECLO"
              value={
                ecloUsed ? (
                  <span className="cell__status">
                    <SignalLamp tone="warn" size="sm" label="ECLO used" />
                    {summary.eclo} access{summary.eclo === 1 ? "" : "es"}
                  </span>
                ) : (
                  "none"
                )
              }
            />
            <Fact
              label="Selected week"
              value={selection.week != null ? `Week ${selection.week}` : "all weeks"}
            />
            <Fact
              label="Selected night"
              value={
                selectedNight != null
                  ? `Night ${selectedNight}${nightQualifier}`
                  : "all nights"
              }
            />
          </dl>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Co-share group members</h3>
            {memberships.length === 0 ? (
              <p className="empty">No co-shared possession recorded for this selection.</p>
            ) : (
              <ul className="drawer__groups">
                {memberships.map((membership) => (
                  <li
                    key={`${membership.locationId}-${membership.week}-${membership.group}`}
                    className="drawer__group"
                  >
                    <div className="drawer__group-head">
                      <span className="drawer__group-tag">{membership.group}</span>
                      <code className="drawer__group-loc">{membership.locationId}</code>
                      <span className="drawer__group-week">W{membership.week}</span>
                    </div>
                    <div className="drawer__group-members">
                      {membership.members.map((member) =>
                        member.activityId === selection.activityId ? (
                          <span
                            key={member.activityId}
                            className="drawer__member drawer__member--self"
                          >
                            {member.activityId}
                          </span>
                        ) : (
                          <button
                            key={member.activityId}
                            type="button"
                            className="drawer__member"
                            onClick={() =>
                              onSelect(
                                selectionForPossession(
                                  member,
                                  membership.week,
                                  selectedNight,
                                ),
                              )
                            }
                          >
                            {member.activityId}
                          </button>
                        ),
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Location capacity status</h3>
            {readings.length === 0 ? (
              <p className="empty">No capacity-bearing occupancy for this selection.</p>
            ) : (
              <div className="table-wrap">
                <table className="table drawer__table">
                  <thead>
                    <tr>
                      <th scope="col">Location</th>
                      <th scope="col">Week</th>
                      <th scope="col">Used</th>
                      <th scope="col">Supply</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {readings.map((reading) => (
                      <tr key={`${reading.locationId}-${reading.week}`}>
                        <th scope="row">
                          <code>{reading.locationId}</code>
                        </th>
                        <td>W{reading.week}</td>
                        <td>
                          {reading.used}/{reading.capacity}
                        </td>
                        <td>{reading.capacity}</td>
                        <td>
                          <span className="cell__status">
                            <SignalLamp
                              tone={STATUS_TONES[reading.status]}
                              size="sm"
                              label={STATUS_LABELS[reading.status]}
                            />
                            {STATUS_LABELS[reading.status]}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Why here</h3>
            {explanation ? (
              <>
                <p className="drawer__summary">{explanation.summary}</p>
                {explanation.reason_codes.length > 0 ? (
                  <ul className="reasons" aria-label="Reason codes">
                    {explanation.reason_codes.map((code) => (
                      <li key={code} className="reason">
                        <code>{code}</code>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="empty">No reason codes recorded for this activity.</p>
                )}
              </>
            ) : (
              <p className="empty">
                No deterministic explanation is persisted for this activity.
              </p>
            )}
          </section>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Why this week</h3>
            {!explanation ? (
              <p className="empty">
                No deterministic explanation is persisted for this activity, so the
                chosen week cannot be justified from stored evidence.
              </p>
            ) : !displacement.present ? (
              <p className="empty">{displacement.note}</p>
            ) : (
              <>
                <p className="drawer__summary">{displacement.note}</p>
                <dl className="drawer__facts drawer__facts--tight">
                  <Fact
                    label="Planned earliest"
                    value={
                      displacement.plannedEarliestWeek != null
                        ? `Week ${displacement.plannedEarliestWeek}`
                        : "—"
                    }
                  />
                  <Fact
                    label="First access"
                    value={
                      displacement.actualFirstWeek != null
                        ? `Week ${displacement.actualFirstWeek}`
                        : "—"
                    }
                  />
                </dl>
              </>
            )}
          </section>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Why this night</h3>
            {firstAccess && firstNight != null ? (
              <>
                <p className="drawer__summary">
                  The first placed access sits on night {firstNight} (
                  {nightSourceLabel(source)})
                  {firstAccess.eclo ? " and is flagged ECLO" : ""}.
                </p>
                <dl className="drawer__facts drawer__facts--tight">
                  <Fact
                    label="Published physical slot"
                    value={
                      firstAccess.physical_night != null
                        ? `Night ${firstAccess.physical_night}`
                        : "not published"
                    }
                  />
                  <Fact
                    label="Contract-local index"
                    value={`Night ${firstAccess.access_night}`}
                  />
                </dl>
                <p className="drawer__caveat">
                  The physical slot is an internal planning fact, not a record of
                  live personnel presence on site.
                </p>
              </>
            ) : (
              <p className="empty">
                No placed access is persisted for this activity, so no night can be
                shown.
              </p>
            )}
          </section>

          <section className="drawer__section">
            <h3 className="drawer__section-title">Why not earlier</h3>
            {!displacement.present ? (
              <p className="empty">{displacement.note}</p>
            ) : !displacement.displaced ? (
              <p className="drawer__summary">{displacement.note}</p>
            ) : (
              <>
                <p className="drawer__summary">
                  {displacement.trustworthy
                    ? `The earliest admissible start was week ${displacement.plannedEarliestWeek}, but week ${displacement.bindingWeek} rejected the access, so the first access moved to week ${displacement.actualFirstWeek}.`
                    : displacement.note}
                </p>
                {displacement.rejectedWeeks.length > 0 ? (
                  <dl className="drawer__facts drawer__facts--tight">
                    <Fact
                      label="Rejected weeks"
                      value={displacement.rejectedWeeks
                        .map((value) => `W${value}`)
                        .join(", ")}
                    />
                    <Fact
                      label="Binding week"
                      value={
                        displacement.bindingWeek != null
                          ? `W${displacement.bindingWeek}`
                          : "—"
                      }
                    />
                  </dl>
                ) : null}

                {displacement.supportedConstraints.length > 0 ? (
                  <ul className="reasons" aria-label="Binding constraints">
                    {displacement.supportedConstraints.map((code) => (
                      <li key={code} className="reason">
                        <code>{code}</code>
                        <span>{BINDING_LABELS[code] ?? code}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {displacement.supportedConstraints.length > 0 ? (
                  <div className="drawer__binding">
                    {displacement.supportedConstraints.map((code) => {
                      const detail = displacement.bindingDetails[code];
                      const entries =
                        detail && typeof detail === "object"
                          ? Object.entries(detail as Record<string, unknown>).sort(
                              ([left], [right]) => left.localeCompare(right),
                            )
                          : [];
                      return (
                        <div key={code} className="drawer__binding-item">
                          <span className="drawer__binding-code">{code}</span>
                          {entries.length > 0 ? (
                            <dl className="drawer__binding-facts">
                              {entries.map(([key, value]) => (
                                <div key={key} className="drawer__binding-fact">
                                  <dt>{BINDING_DETAIL_LABELS[key] ?? key}</dt>
                                  <dd>{formatDetailValue(value)}</dd>
                                </div>
                              ))}
                            </dl>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}

                {displacement.unsupportedConstraints.length > 0 ? (
                  <p className="explanations__unsupported">
                    No recorded detail confirms{" "}
                    {displacement.unsupportedConstraints.join(", ")}, so the board
                    does not name{" "}
                    {displacement.unsupportedConstraints.length === 1 ? "it" : "them"}{" "}
                    as the cause.
                  </p>
                ) : null}
              </>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
