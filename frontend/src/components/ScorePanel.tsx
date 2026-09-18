import type { SoftScores } from "../api/types";
import { formatNumber, formatScore } from "../lib/format";
import Panel from "./Panel";

interface ScorePanelProps {
  scores: SoftScores;
  scenario: string;
}

const PRIORITY_LABELS: Record<string, string> = {
  "1": "Tier 1 (highest)",
  "2": "Tier 2",
  "3": "Tier 3",
};

export default function ScorePanel({ scores, scenario }: ScorePanelProps) {
  const priority = scores.priority_overrun ?? {};
  const priorityKeys = ["1", "2", "3"].filter((key) => key in priority);

  return (
    <Panel
      title="Score components"
      eyebrow={`Scenario ${scenario} · lower is better`}
      actions={
        <span className="panel__meter">
          formula {scores.formula_version ?? "—"}
        </span>
      }
    >
      <div className="scoreboard">
        <div className="scoreboard__headline">
          <span className="scoreboard__label">Objective score</span>
          <span className="scoreboard__value" data-testid="objective-score">
            {formatScore(scores.objective_score)}
          </span>
          <span className="scoreboard__note">
            {scores.objective_score == null
              ? "Not computed for an infeasible plan."
              : "Penalty total for this scenario objective."}
          </span>
        </div>
        <div className="scoreboard__weighted">
          <span className="scoreboard__label">Priority-weighted overrun</span>
          <span className="scoreboard__value scoreboard__value--sub">
            {formatScore(scores.priority_weighted_score)}
          </span>
        </div>
      </div>

      <ul className="counts counts--wide" aria-label="Score terms">
        <li className="counts__cell">
          <span className="counts__value">
            {formatNumber(scores.overrun_days_total)}
          </span>
          <span className="counts__label">Overrun days total</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">
            {formatNumber(scores.contracts_overrunning)}
          </span>
          <span className="counts__label">Contracts overrunning</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">
            {formatNumber(scores.earliness_days_total)}
          </span>
          <span className="counts__label">Earliness days</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">
            {formatNumber(scores.excess_access_nights_total)}
          </span>
          <span className="counts__label">Excess access-nights</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">
            {formatNumber(scores.eclo_nights_total)}
          </span>
          <span className="counts__label">ECLO nights</span>
        </li>
      </ul>

      {priorityKeys.length > 0 ? (
        <div className="priority">
          <h3 className="subhead">Overrun by contract priority</h3>
          <ul className="bars" aria-label="Overrun days by priority tier">
            {priorityKeys.map((key) => {
              const value = priority[key] ?? 0;
              const max = Math.max(
                1,
                ...priorityKeys.map((k) => priority[k] ?? 0),
              );
              return (
                <li key={key} className="bars__row">
                  <span className="bars__label">{PRIORITY_LABELS[key] ?? key}</span>
                  <span className="bars__track">
                    <span
                      className={`bars__fill bars__fill--tier-${key}`}
                      style={{ width: `${(value / max) * 100}%` }}
                    />
                  </span>
                  <span className="bars__value">{formatNumber(value)} d</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}
