import { formatNumber, formatScore } from "../lib/format";
import {
  buildScenarioComparison,
  type CompareMetric,
  type ScenarioCompareEntry,
  type ScenarioCompareRow,
} from "../lib/compare";
import type { Scenario } from "../api/types";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ScenarioCompareProps {
  entries: ScenarioCompareEntry[];
  loading: boolean;
  error: string | null;
  activeScenario: string;
  onLoadOthers?: () => void;
}

const METRIC_LABELS: Record<CompareMetric, string> = {
  priorityWeightedOverrun: "Priority-weighted overrun",
  excessAccessNights: "Excess access-nights",
  ecloNights: "ECLO nights",
  capacityExcess: "Capacity excess",
};

function bestClass(
  row: ScenarioCompareRow,
  metric: CompareMetric,
  leaders: Record<CompareMetric, Scenario[]>,
): string {
  return leaders[metric].includes(row.scenario) ? " compare__cell--best" : "";
}

function MetricRow({
  label,
  hint,
  rows,
  leaders,
  metric,
  render,
}: {
  label: string;
  hint?: string;
  rows: ScenarioCompareRow[];
  leaders: Record<CompareMetric, Scenario[]>;
  metric: CompareMetric;
  render: (row: ScenarioCompareRow) => string;
}) {
  return (
    <tr>
      <th scope="row">
        {label}
        {hint ? <span className="compare__hint">{hint}</span> : null}
      </th>
      {rows.map((row) => (
        <td key={row.scenario} className={`compare__cell${bestClass(row, metric, leaders)}`}>
          {render(row)}
          {leaders[metric].includes(row.scenario) ? (
            <span className="compare__lead" title={`Lowest ${label.toLowerCase()}`}>
              lowest
            </span>
          ) : null}
        </td>
      ))}
    </tr>
  );
}

export default function ScenarioCompare({
  entries,
  loading,
  error,
  activeScenario,
  onLoadOthers,
}: ScenarioCompareProps) {
  const comparison = buildScenarioComparison(entries);

  return (
    <Panel
      title="Scenario comparison"
      eyebrow="Explain · A/B/C side by side"
      actions={
        <span className="panel__meter">
          {comparison.rows.length}/{3} scenarios loaded
        </span>
      }
    >
      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Could not load comparison</span>
          <p>{error}</p>
        </div>
      ) : null}

      {loading && comparison.rows.length === 0 ? (
        <p className="empty" role="status" aria-live="polite">
          Loading the scenario reports for this run…
        </p>
      ) : null}

      {!loading && !comparison.canCompare ? (
        <div className="compare-empty">
          <p className="empty">
            {comparison.rows.length === 0
              ? "No scenario results are loaded for this run yet."
              : `Only Scenario ${comparison.rows[0].scenario} has a completed result.`}{" "}
            The comparison board needs at least two scenarios from the same run.
          </p>
          <ol className="compare-empty__steps">
            <li>Open Stage 3, Optimise.</li>
            <li>
              Dispatch {comparison.missing.join(", ") || "the other scenarios"} against
              this run.
            </li>
            <li>Return here once those jobs complete.</li>
          </ol>
          {onLoadOthers ? (
            <button type="button" className="btn btn--primary" onClick={onLoadOthers}>
              Go to Optimise
            </button>
          ) : null}
        </div>
      ) : null}

      {comparison.canCompare ? (
        <>
          <p className="compare__active">
            Active result: <code>{activeScenario}</code>. The board reads persisted
            validator reports and never recomputes a scenario here.
          </p>

          <div className="compare__leaders" aria-label="Trade-off leaders">
            {(Object.keys(METRIC_LABELS) as CompareMetric[]).map((metric) => {
              const leaders = comparison.leaders[metric];
              return (
                <span key={metric} className="compare__leader-chip">
                  <span className="compare__leader-label">
                    {METRIC_LABELS[metric]}
                  </span>
                  <strong>
                    {leaders.length > 0 ? leaders.map((s) => `Scenario ${s}`).join(", ") : "no data"}
                  </strong>
                </span>
              );
            })}
          </div>

          <div className="table-wrap">
            <table className="table compare">
              <caption className="sr-only">
                Scenario A, B and C results compared on the persisted report fields
              </caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  {comparison.rows.map((row) => (
                    <th key={row.scenario} scope="col">
                      {row.spec.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Capacity policy</th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario} className="cell--wrap">
                      {row.spec.capacity}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">
                    Capacity hotspots
                    <span className="compare__hint">from report detail</span>
                  </th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario}>
                      {formatNumber(row.capacityHotspots)} location-weeks ·{" "}
                      {formatNumber(row.capacityExcess)} excess
                    </td>
                  ))}
                </tr>
                <MetricRow
                  label="Priority-weighted overrun"
                  rows={comparison.rows}
                  leaders={comparison.leaders}
                  metric="priorityWeightedOverrun"
                  render={(row) => formatScore(row.priorityWeightedOverrun)}
                />
                <tr>
                  <th scope="row">Overrun days</th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario}>
                      {formatNumber(row.overrunDaysTotal)} d ·{" "}
                      {formatNumber(row.contractsOverrunning)} contracts
                    </td>
                  ))}
                </tr>
                <MetricRow
                  label="Excess access-nights"
                  rows={comparison.rows}
                  leaders={comparison.leaders}
                  metric="excessAccessNights"
                  render={(row) => formatNumber(row.excessAccessNights)}
                />
                <MetricRow
                  label="ECLO nights"
                  hint="soft score and report detail"
                  rows={comparison.rows}
                  leaders={comparison.leaders}
                  metric="ecloNights"
                  render={(row) => `${formatNumber(row.ecloNights)}`}
                />
                <tr>
                  <th scope="row">Nights scheduled</th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario}>{formatNumber(row.nightsScheduled)}</td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">Result state</th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario}>
                      <span className="cell__status">
                        <SignalLamp
                          tone={row.feasible ? "ok" : "danger"}
                          size="sm"
                          label={row.feasible ? "Feasible" : "Infeasible"}
                        />
                        {row.feasible ? "feasible" : "infeasible"}
                      </span>
                      <span className="cell__status">
                        <SignalLamp
                          tone={row.readyForSubmission ? "ok" : "warn"}
                          size="sm"
                          label={
                            row.readyForSubmission
                              ? "Ready for submission"
                              : "Not ready for submission"
                          }
                        />
                        {row.readyForSubmission ? "ready" : "not ready"}
                      </span>
                      <span className="compare__authority">
                        authority {row.authority}
                      </span>
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">Overrun by tier</th>
                  {comparison.rows.map((row) => (
                    <td key={row.scenario}>
                      {["1", "2", "3"].map((tier) => (
                        <span key={tier} className="compare__tier">
                          T{tier} {formatNumber(row.priorityOverrun[tier] ?? 0)} d
                        </span>
                      ))}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <p className="compare__foot">
            Lower is better for the highlighted rows. Capacity policy text is the
            published scenario copy; every number is read from the validator
            <code> soft_scores</code> and <code>detail</code> fields.
          </p>
        </>
      ) : null}
    </Panel>
  );
}
