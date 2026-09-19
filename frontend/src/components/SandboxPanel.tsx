import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, createSandbox } from "../api/client";
import type { NetworkResponse, SandboxRead } from "../api/types";
import {
  buildSandboxRequest,
  describeApplied,
  fragilityReading,
  isSandboxVariantUsable,
  MAX_FRAGILITY_TRIALS,
  MAX_SANDBOX_SEED,
  MIN_FRAGILITY_TRIALS,
  newSandboxDraft,
  projectSandboxMetrics,
  sandboxStatusLabel,
  sandboxStatusTone,
  SANDBOX_SCENARIOS,
  type SandboxDraft,
} from "../lib/sandbox";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface SandboxPanelProps {
  runId: string;
  jobId: string;
  scenario: string;
  network: NetworkResponse;
}

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
  const tone = sandboxStatusTone(status);
  if (tone === "ok") return "ok";
  if (tone === "warn") return "warn";
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

function SandboxVariant({ read, scenario }: { read: SandboxRead; scenario: string }) {
  const metrics = projectSandboxMetrics(read);
  const fragility = fragilityReading(read.fragility);
  const usable = isSandboxVariantUsable(read.variant);
  const applied = describeApplied(read.applied);
  const reasons = read.variant.infeasibility_reasons ?? [];
  const status = sandboxStatusLabel(read.variant.status);
  const sourceScenario = read.source_scenario ?? scenario;

  return (
    <div className="sandbox__result">
      <div
        className={`notice notice--${usable ? "ok" : "danger"}`}
        role="status"
        aria-live="polite"
      >
        <span className="notice__title">
          <SignalLamp
            tone={sandboxStatusTone(read.variant.status)}
            size="sm"
            label={`Variant ${status}`}
          />
          <span> Variant {status}</span>
        </span>
        <p>
          {usable
            ? "The variant passed the independent physical witness. It is an advisory what-if that leaves the source job untouched."
            : status === "UNSAFE"
              ? "The independent physical witness rejected this variant, so the server withheld the schedule. Do not adopt it."
              : status === "INFEASIBLE"
                ? "No schedule satisfies the variant instance. The what-if is honestly infeasible."
                : "The solver did not prove a usable variant. Treat the outcome as unproven, not as adoptable."}
        </p>
        {!usable && reasons.length > 0 ? (
          <ul className="notice__list">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <p className="sandbox__caveat">
          Advisory and exploratory. The what-if re-solves on the server and never
          rewrites this job&apos;s published CSVs or validated result. Scenario{" "}
          {sourceScenario} is the source schedule.
        </p>
      </div>

      <div className="sandbox__section">
        <h3 className="subhead">
          Baseline vs variant
          <span className="subhead__meter">delta is variant − baseline</span>
        </h3>
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">
              Objective facts for the source schedule and the what-if variant
            </caption>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Baseline {sourceScenario}</th>
                <th scope="col">Variant</th>
                <th scope="col">Delta</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric) => (
                <tr key={metric.key}>
                  <th scope="row" title={metric.hint}>
                    {metric.label}
                  </th>
                  <td>{metric.baselineText}</td>
                  <td>{metric.variantText}</td>
                  <td>
                    <span
                      className={`sandbox__delta sandbox__delta--${metric.tone}`}
                    >
                      {metric.deltaText}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="panel__hint">
          Improvements are green, worsenings are amber. Access nights are a
          plain count with no direction.
        </p>
      </div>

      <div className="sandbox__section">
        <h3 className="subhead">
          Fragility signal
          <span className="subhead__meter">
            {fragility.present ? `${fragility.trials} trials` : "not requested"}
          </span>
        </h3>
        <div
          className={`notice notice--${fragility.tone === "ok" ? "ok" : fragility.tone === "warn" ? "warn" : "danger"}`}
        >
          <span className="notice__title">
            <SignalLamp
              tone={fragility.tone}
              size="sm"
              label={fragility.headline}
            />
            <span> {fragility.headline}</span>
          </span>
          <p>{fragility.detail}</p>
          {read.fragility ? (
            <dl className="sandbox__facts">
              <div>
                <dt>Base supply</dt>
                <dd>{read.fragility.base_supply}</dd>
              </div>
              <div>
                <dt>Feasible floor</dt>
                <dd>{read.fragility.feasible_floor ?? "—"}</dd>
              </div>
              <div>
                <dt>Breaking supply</dt>
                <dd>{read.fragility.breaking_new_supply ?? "—"}</dd>
              </div>
              <div>
                <dt>Smallest reduction</dt>
                <dd>{read.fragility.smallest_supply_reduction ?? "—"}</dd>
              </div>
              <div>
                <dt>Bounded search</dt>
                <dd>{read.fragility.bounded ? "yes" : "no"}</dd>
              </div>
            </dl>
          ) : null}
        </div>
      </div>

      <div className="sandbox__section">
        <h3 className="subhead">Applied knobs</h3>
        {applied.length > 0 ? (
          <ul className="sandbox__applied">
            {applied.map((item) => (
              <li key={item}>
                <code>{item}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">
            No knob changed. The variant is the unmodified re-solve.
          </p>
        )}
      </div>
    </div>
  );
}

export default function SandboxPanel({
  runId,
  jobId,
  scenario,
  network,
}: SandboxPanelProps) {
  const [draft, setDraft] = useState<SandboxDraft>(newSandboxDraft);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SandboxRead | null>(null);

  // A different completed job needs a clean composer and no stale outcome.
  useEffect(() => {
    setDraft(newSandboxDraft());
    setFormErrors([]);
    setError(null);
    setResult(null);
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
      sortedUnique(
        network.contracts.map((contract) => contract.contract_number),
      ),
    [network],
  );

  const patch = (fields: Partial<SandboxDraft>) =>
    setDraft((current) => ({ ...current, ...fields }));

  const submit = async () => {
    const built = buildSandboxRequest(draft);
    setFormErrors(built.errors);
    setError(null);
    if (!built.ok || !built.payload) return;
    setSubmitting(true);
    try {
      const read = await createSandbox(runId, jobId, built.payload);
      setResult(read);
    } catch (caught) {
      setResult(null);
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  const tone = result ? panelTone(result.variant.status) : "default";

  return (
    <Panel
      title="What-if sandbox"
      eyebrow={`Bonus · F-BONUS-002 · scenario ${scenario}`}
      tone={tone}
      actions={
        <span className="panel__meter">
          {result
            ? `variant ${sandboxStatusLabel(result.variant.status)}`
            : "advisory re-solve"}
        </span>
      }
    >
      <p className="replan__intro">
        Vary one or more controlled knobs and re-solve scenario {scenario} on the
        server. The board compares the source schedule with the variant and can
        probe how fragile a location is to a supply cut. The browser never
        solves. Nothing here changes the published CSVs or the validated result.
      </p>

      <fieldset className="replan__composer" disabled={submitting}>
        <legend className="sr-only">Controlled what-if knobs</legend>

        <div className="replan__grid">
          <Field
            label="Scenario"
            hint="Blank keeps the source scenario."
          >
            <select
              value={draft.scenario}
              onChange={(event) => patch({ scenario: event.target.value as SandboxDraft["scenario"] })}
            >
              <option value="">
                Inherit source ({scenario})
              </option>
              {SANDBOX_SCENARIOS.map((option) => (
                <option key={option} value={option}>
                  Scenario {option}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="ECLO allowed"
            hint="Blank keeps the scenario policy."
          >
            <select
              value={draft.ecloAllowed}
              onChange={(event) =>
                patch({
                  ecloAllowed: event.target.value as SandboxDraft["ecloAllowed"],
                })
              }
            >
              <option value="inherit">Inherit scenario policy</option>
              <option value="true">Allow ECLO</option>
              <option value="false">Disallow ECLO</option>
            </select>
          </Field>

          <Field
            label="Supply override"
            hint="Whole number of nightly possessions, 0 or more."
          >
            <span className="sandbox__pair">
              <select
                value={draft.supplyLocationId}
                onChange={(event) =>
                  patch({ supplyLocationId: event.target.value })
                }
              >
                <option value="">Select location…</option>
                {locations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                step={1}
                inputMode="numeric"
                value={draft.supplyValue}
                onChange={(event) => patch({ supplyValue: event.target.value })}
              />
            </span>
          </Field>

          <Field
            label="Workfront override"
            hint="Whole number of workfronts, 1 or more."
          >
            <span className="sandbox__pair">
              <select
                value={draft.workfrontContract}
                onChange={(event) =>
                  patch({ workfrontContract: event.target.value })
                }
              >
                <option value="">Select contract…</option>
                {contracts.map((contract) => (
                  <option key={contract} value={contract}>
                    {contract}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={draft.workfrontValue}
                onChange={(event) => patch({ workfrontValue: event.target.value })}
              />
            </span>
          </Field>

          <Field
            label="Horizon extension (weeks)"
            hint="Blank keeps the configured default."
          >
            <input
              type="number"
              min={0}
              step={1}
              inputMode="numeric"
              placeholder="configured default"
              value={draft.horizonExtensionWeeks}
              onChange={(event) =>
                patch({ horizonExtensionWeeks: event.target.value })
              }
            />
          </Field>

          <Field
            label="Fragility location"
            hint="Find the smallest supply cut that breaks feasibility."
          >
            <select
              value={draft.fragilityLocationId}
              onChange={(event) =>
                patch({ fragilityLocationId: event.target.value })
              }
            >
              <option value="">No fragility probe</option>
              {locations.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </Field>
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
              value={draft.timeLimitSeconds}
              onChange={(event) =>
                patch({ timeLimitSeconds: event.target.value })
              }
            />
          </Field>
          <Field label="Solver seed (optional)" hint="Pin the seed to reproduce.">
            <input
              type="number"
              min={0}
              max={MAX_SANDBOX_SEED}
              step={1}
              inputMode="numeric"
              placeholder="server default"
              value={draft.seed}
              onChange={(event) => patch({ seed: event.target.value })}
            />
          </Field>
          <Field
            label={`Fragility trials (${MIN_FRAGILITY_TRIALS}–${MAX_FRAGILITY_TRIALS})`}
            hint="Bounded search budget for the fragility probe."
          >
            <input
              type="number"
              min={MIN_FRAGILITY_TRIALS}
              max={MAX_FRAGILITY_TRIALS}
              step={1}
              inputMode="numeric"
              value={draft.fragilityMaxTrials}
              onChange={(event) =>
                patch({ fragilityMaxTrials: event.target.value })
              }
            />
          </Field>
        </div>
      </fieldset>

      {formErrors.length > 0 ? (
        <div className="notice notice--warn" role="alert">
          <span className="notice__title">Check the knob set</span>
          <ul className="notice__list">
            {formErrors.map((message, index) => (
              <li key={`${index}-${message}`}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Sandbox request failed</span>
          <p>{error}</p>
        </div>
      ) : null}

      <div className="panel__footer">
        <span className="panel__hint">
          {result
            ? "Run again with a different knob or seed to compare."
            : "No what-if has been run for this job yet."}
        </span>
        <button
          type="button"
          className="btn btn--primary"
          onClick={submit}
          disabled={submitting}
        >
          {submitting ? "Running the what-if…" : "Run what-if"}
        </button>
      </div>

      {submitting ? (
        <p className="empty" role="status" aria-live="polite">
          Re-solving the variant and checking the physical witness…
        </p>
      ) : null}

      {!submitting && !result && !error ? (
        <p className="empty" role="status" aria-live="polite">
          Pick at least one knob or a fragility location, then run the what-if to
          compare baseline and variant metrics.
        </p>
      ) : null}

      {result ? <SandboxVariant read={result} scenario={scenario} /> : null}
    </Panel>
  );
}
