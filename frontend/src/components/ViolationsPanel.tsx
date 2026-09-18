import type { HardViolation } from "../api/types";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ViolationsPanelProps {
  violations: HardViolation[];
}

const RULE_LABELS: Record<string, string> = {
  workload: "Workload completeness",
  planned_start: "Planned start",
  predecessor: "Predecessor ordering",
  closure: "Closure / buffer",
  mirror: "Live opposite-bound mirroring",
  interchange: "Live interchange",
  mix: "Possession mix",
  capacity: "Location capacity",
  allocation: "Weekly allocation",
  workfront: "Workfront cap",
  eclo: "ECLO policy",
  planned_date: "Planned completion date",
  eclo_window: "ECLO continuity window",
};

export default function ViolationsPanel({ violations }: ViolationsPanelProps) {
  const grouped = new Map<string, HardViolation[]>();
  for (const violation of violations) {
    const bucket = grouped.get(violation.rule) ?? [];
    bucket.push(violation);
    grouped.set(violation.rule, bucket);
  }

  return (
    <Panel
      title="Hard violations"
      eyebrow="Rule breaches block submission"
      tone={violations.length > 0 ? "danger" : "ok"}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={violations.length > 0 ? "danger" : "ok"}
            size="sm"
            label={violations.length > 0 ? "Violations present" : "No violations"}
          />
          <span>
            {violations.length} {violations.length === 1 ? "breach" : "breaches"}
          </span>
        </span>
      }
    >
      {violations.length === 0 ? (
        <p className="empty empty--ok">
          No hard-rule violations. The schedule is physically and contractually clean.
        </p>
      ) : (
        <div className="violations">
          {[...grouped.entries()].map(([rule, items]) => (
            <div key={rule} className="violations__group">
              <h3 className="violations__rule">
                <code>{rule}</code>
                <span>{RULE_LABELS[rule] ?? rule}</span>
                <span className="violations__count">{items.length}</span>
              </h3>
              <ul className="violations__list">
                {items.map((violation, index) => (
                  <li key={index}>{violation.detail}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
