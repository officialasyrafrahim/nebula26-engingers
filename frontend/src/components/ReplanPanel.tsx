import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError, createReplan } from "../api/client";
import type {
  Disruption,
  DisruptionKind,
  NetworkResponse,
  ReplanRead,
} from "../api/types";
import {
  buildReplanRequest,
  classifyReplanStatus,
  describeDisruption,
  DISRUPTION_KIND_LABEL,
  formatChurnSummary,
  isReplanUsable,
  newDisruptionDraft,
  newReplanOptions,
  PHYSICAL_NIGHT_MAX,
  PHYSICAL_NIGHT_MIN,
  projectMoved,
  replanStatusLabel,
  replanStatusTone,
  summariseDiff,
  summariseImpact,
  type DisruptionDraft,
  type ReplanOptionsDraft,
} from "../lib/replan";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ReplanPanelProps {
  runId: string;
  jobId: string;
  scenario: string;
  network: NetworkResponse;
}

const KIND_ORDER: DisruptionKind[] = [
  "supply_drop",
  "location_unavailable",
  "night_unavailable",
  "urgent_activity",
];

function errorMessage(caught: unknown): string {
  return caught instanceof ApiError
    ? caught.message
    : caught instanceof Error
      ? caught.message
      : String(caught);
}

function sortedUnique(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

function panelTone(status: string): "ok" | "warn" | "danger" {
  const kind = classifyReplanStatus(status);
  if (kind === "feasible") return "ok";
  if (kind === "unknown") return "warn";
  return "danger";
}

interface FieldProps {
  label: string;
  hint?: string;
  children: ReactNode;
}

function Field({ label, hint, children }: FieldProps) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint ? <span className="field__hint">{hint}</span> : null}
    </label>
  );
}

interface DisruptionEditorProps {
  draft: DisruptionDraft;
  index: number;
  locations: string[];
  contracts: string[];
  activities: string[];
  disabled: boolean;
  removable: boolean;
  onChange: (id: string, patch: Partial<DisruptionDraft>) => void;
  onRemove: (id: string) => void;
}

function DisruptionEditor({
  draft,
  index,
  locations,
  contracts,
  activities,
  disabled,
  removable,
  onChange,
  onRemove,
}: DisruptionEditorProps) {
  const set = (patch: Partial<DisruptionDraft>) => onChange(draft.id, patch);

  return (
    <fieldset className="replan__draft" disabled={disabled}>
      <div className="replan__draft-head">
        <span className="replan__draft-index">Disruption {index + 1}</span>
        <label className="replan__draft-kind">
          <span className="sr-only">Disruption kind</span>
          <select
            value={draft.kind}
            onChange={(event) =>
              set({ kind: event.target.value as DisruptionKind })
            }
          >
            {KIND_ORDER.map((kind) => (
              <option key={kind} value={kind}>
                {DISRUPTION_KIND_LABEL[kind]}
              </option>
            ))}
          </select>
        </label>
        {removable ? (
          <button
            type="button"
            className="btn btn--tiny btn--danger"
            onClick={() => onRemove(draft.id)}
          >
            Remove
          </button>
        ) : null}
      </div>

      <div className="replan__grid">
        {draft.kind === "supply_drop" ? (
          <>
            <Field label="Location" hint="A location in this run's compiled network.">
              <select
                value={draft.locationId}
                onChange={(event) => set({ locationId: event.target.value })}
              >
                <option value="">Select location…</option>
                {locations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="New supply" hint="Whole number of nightly possessions, 0 or more.">
              <input
                type="number"
                min={0}
                step={1}
                inputMode="numeric"
                value={draft.newSupply}
                onChange={(event) => set({ newSupply: event.target.value })}
              />
            </Field>
          </>
        ) : null}

        {draft.kind === "location_unavailable" ? (
          <>
            <Field label="Location" hint="A location in this run's compiled network.">
              <select
                value={draft.locationId}
                onChange={(event) => set({ locationId: event.target.value })}
              >
                <option value="">Select location…</option>
                {locations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Weeks" hint="Blank closes every week. Otherwise 1, 3, 4.">
              <input
                type="text"
                placeholder="all weeks"
                value={draft.weeks}
                onChange={(event) => set({ weeks: event.target.value })}
              />
            </Field>
          </>
        ) : null}

        {draft.kind === "night_unavailable" ? (
          <>
            <Field label="Physical night" hint="1 to 7 within each planning week.">
              <select
                value={draft.physicalNight}
                onChange={(event) => set({ physicalNight: event.target.value })}
              >
                {Array.from(
                  { length: PHYSICAL_NIGHT_MAX - PHYSICAL_NIGHT_MIN + 1 },
                  (_, offset) => PHYSICAL_NIGHT_MIN + offset,
                ).map((night) => (
                  <option key={night} value={String(night)}>
                    Night {night}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Weeks" hint="Blank closes every week. Otherwise 1, 3, 4.">
              <input
                type="text"
                placeholder="all weeks"
                value={draft.weeks}
                onChange={(event) => set({ weeks: event.target.value })}
              />
            </Field>
          </>
        ) : null}

        {draft.kind === "urgent_activity" ? (
          <>
            <Field label="Activity id">
              <input
                type="text"
                placeholder="U1"
                value={draft.activityId}
                onChange={(event) => set({ activityId: event.target.value })}
              />
            </Field>
            <Field label="Contract">
              <select
                value={draft.contractNumber}
                onChange={(event) => set({ contractNumber: event.target.value })}
              >
                <option value="">Select contract…</option>
                {contracts.map((contract) => (
                  <option key={contract} value={contract}>
                    {contract}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Start location">
              <select
                value={draft.startLocationId}
                onChange={(event) => set({ startLocationId: event.target.value })}
              >
                <option value="">Select location…</option>
                {locations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="End location">
              <select
                value={draft.endLocationId}
                onChange={(event) => set({ endLocationId: event.target.value })}
              >
                <option value="">Select location…</option>
                {locations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Total accesses">
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={draft.totalAccesses}
                onChange={(event) => set({ totalAccesses: event.target.value })}
              />
            </Field>
            <Field label="Planned start date">
              <input
                type="date"
                value={draft.plannedStartDate}
                onChange={(event) =>
                  set({ plannedStartDate: event.target.value })
                }
              />
            </Field>
            <Field label="Priority" hint="1 is highest, 3 is lowest.">
              <select
                value={draft.activityPriority}
                onChange={(event) => set({ activityPriority: event.target.value })}
              >
                <option value="1">1 · highest</option>
                <option value="2">2 · middle</option>
                <option value="3">3 · lowest</option>
              </select>
            </Field>
            <Field label="Predecessor" hint="Optional. Must finish first.">
              <select
                value={draft.predecessorActivityId}
                onChange={(event) =>
                  set({ predecessorActivityId: event.target.value })
                }
              >
                <option value="">None</option>
                {activities.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Activity type" hint="Optional override of the contract type.">
              <input
                type="text"
                placeholder="contract default"
                value={draft.activityType}
                onChange={(event) => set({ activityType: event.target.value })}
              />
            </Field>
          </>
        ) : null}
      </div>
    </fieldset>
  );
}

interface ActivityListProps {
  label: string;
  ids: string[];
  tone?: "ok" | "warn" | "danger" | "info" | "idle";
  emptyText: string;
}

function ActivityList({ label, ids, tone = "idle", emptyText }: ActivityListProps) {
  if (ids.length === 0) {
    return (
      <div className="replan__list">
        <h3 className="subhead">
          {label}
          <span className="subhead__meter">0</span>
        </h3>
        <p className="empty">{emptyText}</p>
      </div>
    );
  }
  return (
    <div className="replan__list">
      <h3 className="subhead">
        {label}
        <span className="subhead__meter">{ids.length}</span>
      </h3>
      <ul className="replan__pills">
        {ids.map((id) => (
          <li key={id} className={`replan__pill replan__pill--${tone}`}>
            <code>{id}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReplanOutcome({ replan }: { replan: ReplanRead }) {
  const diff = summariseDiff(replan.diff);
  const impact = summariseImpact(replan.impact);
  const moved = projectMoved(replan.diff);
  const usable = isReplanUsable(replan);
  const status = classifyReplanStatus(replan.status);
  const reasons = replan.result?.infeasibility_reasons ?? [];
  const composed = replan.disruption ?? [];

  return (
    <div className="replan__result">
      <div
        className={`notice notice--${usable ? "ok" : "danger"}`}
        role="status"
        aria-live="polite"
      >
        <span className="notice__title">
          <SignalLamp
            tone={replanStatusTone(replan.status)}
            size="sm"
            label={`Replan ${replanStatusLabel(replan.status)}`}
          />
          <span> Replan status {replanStatusLabel(replan.status)}</span>
        </span>
        <p>
          {usable
            ? "The replan passed the independent physical witness. It is a usable what-if that leaves the source job untouched."
            : status === "unsafe"
              ? "The independent physical witness rejected this replan, so the server withheld the schedule. Do not use it."
              : status === "infeasible"
                ? "No schedule satisfies the disrupted instance. Do not use it."
                : "The solver did not prove a usable outcome. Do not treat it as adoptable."}
        </p>
        {!usable && reasons.length > 0 ? (
          <ul className="notice__list">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <p className="replan__caveat">
          A replan is a what-if. It is stored beside the run and never rewrites
          this job&apos;s three published CSVs. Scenario {replan.scenario} source
          schedule is unchanged.
        </p>
      </div>

      <div className="replan__metrics">
        <div className="replan__metric">
          <span className="replan__metric-value">{replan.churn_cost}</span>
          <span className="replan__metric-label">Churn cost</span>
          <span className="replan__metric-note">
            {formatChurnSummary(replan.churn_cost, diff.originalAccesses)}
          </span>
        </div>
        <div className="replan__metric">
          <span className="replan__metric-value">{diff.movedActivities}</span>
          <span className="replan__metric-label">Activities moved</span>
          <span className="replan__metric-note">
            {diff.movedAccesses} accesses relocated
          </span>
        </div>
        <div className="replan__metric">
          <span className="replan__metric-value">{diff.reusedAccesses}</span>
          <span className="replan__metric-label">Accesses reused</span>
          <span className="replan__metric-note">
            of {diff.originalAccesses} original placements
          </span>
        </div>
        <div className="replan__metric">
          <span className="replan__metric-value">
            {diff.unsatisfiableActivities}
          </span>
          <span className="replan__metric-label">Newly unsatisfiable</span>
          <span className="replan__metric-note">
            {impact.invalidPlacements} invalid placements
          </span>
        </div>
      </div>

      <div className="replan__section">
        <h3 className="subhead">
          Impact assessment
          <span className="subhead__meter">
            {impact.affectedActivities} activities · {impact.affectedContracts}{" "}
            contracts
          </span>
        </h3>
        <dl className="replan__facts">
          <div>
            <dt>Invalid placements</dt>
            <dd>{impact.invalidPlacements}</dd>
          </div>
          <div>
            <dt>Affected contracts</dt>
            <dd>{impact.affectedContracts}</dd>
          </div>
          <div>
            <dt>Affected location-weeks</dt>
            <dd>{impact.affectedLocationWeeks}</dd>
          </div>
          <div>
            <dt>Injected access-nights</dt>
            <dd>{impact.injectedAccessNights}</dd>
          </div>
          <div>
            <dt>Access-nights before → lower bound</dt>
            <dd>
              {impact.accessNightsBefore} → {impact.accessNightsAfter}
            </dd>
          </div>
        </dl>
        {impact.affectedActivities > 0 ? (
          <ActivityList
            label="Affected activities"
            ids={replan.impact.affected_activities}
            tone="warn"
            emptyText="None."
          />
        ) : null}
        {impact.affectedContracts > 0 ? (
          <ActivityList
            label="Affected contracts"
            ids={replan.impact.affected_contracts}
            tone="warn"
            emptyText="None."
          />
        ) : null}
        {replan.impact.notes.length > 0 ? (
          <ul className="replan__notes">
            {replan.impact.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="replan__section">
        <h3 className="subhead">
          Before / after diff
          <span className="subhead__meter">
            {diff.hasChanges ? "placements changed" : "no placements changed"}
          </span>
        </h3>
        {moved.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">
                Activities moved by the replan, with their source and target
                week and physical night
              </caption>
              <thead>
                <tr>
                  <th scope="col">Activity</th>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                </tr>
              </thead>
              <tbody>
                {moved.map((row) => (
                  <tr key={row.activityId}>
                    <th scope="row">
                      <code>{row.activityId}</code>
                    </th>
                    <td className="cell--danger">
                      {row.from.join(", ") || "—"}
                    </td>
                    <td className="cell--warn">{row.to.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty empty--ok">
            No activity moved. Every original placement was reused.
          </p>
        )}

        <div className="replan__lists">
          <ActivityList
            label="Unchanged"
            ids={replan.diff.unchanged}
            tone="ok"
            emptyText="No activity kept its exact placements."
          />
          <ActivityList
            label="Added"
            ids={replan.diff.added}
            tone="info"
            emptyText="No activity was added."
          />
          <ActivityList
            label="Removed"
            ids={replan.diff.removed}
            tone="warn"
            emptyText="No activity was removed."
          />
          <ActivityList
            label="Newly unsatisfiable"
            ids={replan.diff.newly_unsatisfiable}
            tone="danger"
            emptyText="Every required activity is placed."
          />
        </div>
      </div>

      <div className="replan__section">
        <h3 className="subhead">Disruptions assessed</h3>
        <ul className="replan__composed">
          {composed.map((item: Disruption, index: number) => (
            <li
              key={`${index}-${item.kind}`}
              className="replan__composed-item"
            >
              <code>{item.kind}</code>
              <span>{describeDisruption(item)}</span>
            </li>
          ))}
        </ul>
        {composed.length === 0 ? (
          <p className="empty">The server returned no disruption record.</p>
        ) : null}
      </div>
    </div>
  );
}

export default function ReplanPanel({
  runId,
  jobId,
  scenario,
  network,
}: ReplanPanelProps) {
  const [drafts, setDrafts] = useState<DisruptionDraft[]>(() => [
    newDisruptionDraft("draft-1"),
  ]);
  const nextDraftId = useRef(2);
  const [options, setOptions] = useState<ReplanOptionsDraft>(newReplanOptions);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replan, setReplan] = useState<ReplanRead | null>(null);

  // A different completed job needs a clean composer. The source schedule and
  // any previous outcome belong to the previous job.
  useEffect(() => {
    setDrafts([newDisruptionDraft("draft-1")]);
    nextDraftId.current = 2;
    setOptions(newReplanOptions());
    setFormErrors([]);
    setError(null);
    setReplan(null);
  }, [runId, jobId]);

  const locations = useMemo(
    () =>
      sortedUnique([
        ...network.locations.map((location) => location.location_id),
        ...Object.keys(network.location_capacities ?? {}),
      ]),
    [network],
  );
  const contracts = useMemo(
    () =>
      sortedUnique(network.contracts.map((contract) => contract.contract_number)),
    [network],
  );
  const activities = useMemo(
    () => sortedUnique(network.activities.map((activity) => activity.activity_id)),
    [network],
  );

  const updateDraft = (id: string, patch: Partial<DisruptionDraft>) => {
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft)),
    );
  };

  const addDraft = () => {
    const id = `draft-${nextDraftId.current++}`;
    setDrafts((current) => [...current, newDisruptionDraft(id)]);
  };

  const removeDraft = (id: string) => {
    setDrafts((current) => current.filter((draft) => draft.id !== id));
  };

  const submit = async () => {
    const built = buildReplanRequest(drafts, options);
    setFormErrors(built.errors);
    setError(null);
    if (!built.ok || !built.payload) return;
    setSubmitting(true);
    try {
      const result = await createReplan(runId, jobId, built.payload);
      setReplan(result);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  const tone = replan ? panelTone(replan.status) : "default";

  return (
    <Panel
      title="Disruption replan"
      eyebrow={`Bonus · F-BONUS-001 · scenario ${scenario}`}
      tone={tone}
      actions={
        <span className="panel__meter">
          {replan
            ? `status ${replanStatusLabel(replan.status)}`
            : "minimal-churn what-if"}
        </span>
      }
    >
      <p className="replan__intro">
        Compose one or more mid-horizon disruptions against scenario{" "}
        {scenario}&apos;s completed schedule. The server impact-assesses them and
        re-solves with a churn penalty that rewards keeping the original
        placements. The browser never solves. The replan is stored beside the run
        and never rewrites this job&apos;s three published CSVs.
      </p>

      <fieldset className="replan__composer" disabled={submitting}>
        <legend className="sr-only">Disruption composer</legend>
        {drafts.map((draft, index) => (
          <DisruptionEditor
            key={draft.id}
            draft={draft}
            index={index}
            locations={locations}
            contracts={contracts}
            activities={activities}
            disabled={submitting}
            removable={drafts.length > 1}
            onChange={updateDraft}
            onRemove={removeDraft}
          />
        ))}
      </fieldset>

      <div className="replan__composer-actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={addDraft}
          disabled={submitting}
        >
          Add disruption
        </button>
        <span className="panel__hint">
          {drafts.length} disruption{drafts.length === 1 ? "" : "s"} in the set
        </span>
      </div>

      <div className="replan__options">
        <Field
          label="Time limit (seconds, optional)"
          hint="Blank uses the source job's limit, then the server default."
        >
          <input
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder="source job default"
            value={options.timeLimitSeconds}
            onChange={(event) =>
              setOptions((current) => ({
                ...current,
                timeLimitSeconds: event.target.value,
              }))
            }
          />
        </Field>
        <Field label="Solver seed (optional)" hint="Pin the seed to reproduce.">
          <input
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            placeholder="server default"
            value={options.seed}
            onChange={(event) =>
              setOptions((current) => ({ ...current, seed: event.target.value }))
            }
          />
        </Field>
        <Field
          label="Horizon extension (weeks, optional)"
          hint="Blank uses the configured default."
        >
          <input
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            placeholder="configured default"
            value={options.horizonExtensionWeeks}
            onChange={(event) =>
              setOptions((current) => ({
                ...current,
                horizonExtensionWeeks: event.target.value,
              }))
            }
          />
        </Field>
      </div>

      {formErrors.length > 0 ? (
        <div className="notice notice--warn" role="alert">
          <span className="notice__title">Check the disruption set</span>
          <ul className="notice__list">
            {formErrors.map((message, index) => (
              <li key={`${index}-${message}`}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Replan failed</span>
          <p>{error}</p>
        </div>
      ) : null}

      <div className="panel__footer">
        <span className="panel__hint">
          {replan
            ? "Re-run with a different seed or disruption set to compare."
            : "No replan has been submitted for this job yet."}
        </span>
        <button
          type="button"
          className="btn btn--primary"
          onClick={submit}
          disabled={submitting}
        >
          {submitting ? "Assessing and replanning…" : "Assess and replan"}
        </button>
      </div>

      {submitting ? (
        <p className="empty" role="status" aria-live="polite">
          Running the impact assessment and the minimal-churn solve…
        </p>
      ) : null}

      {!submitting && !replan && !error ? (
        <p className="empty" role="status" aria-live="polite">
          Add a disruption above and submit to see the impact assessment and the
          before/after diff. No schedule leaves the server.
        </p>
      ) : null}

      {replan ? <ReplanOutcome replan={replan} /> : null}
    </Panel>
  );
}
