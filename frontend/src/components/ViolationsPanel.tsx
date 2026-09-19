import type { Authority, HardViolation } from "../api/types";
import { deriveAuthorityClaim, violationCleanSummary } from "../lib/assurance";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ViolationsPanelProps {
  violations: HardViolation[];
  authority?: Authority | string;
  validatorSource?: Authority | string | null;
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

export default function ViolationsPanel({
  violations,
  authority,
  validatorSource,
}: ViolationsPanelProps) {
  const claim = deriveAuthorityClaim(authority ?? "", validatorSource);
  const grouped = new Map<string, HardViolation[]>();
  for (const violation of violations) {
    const bucket = grouped.get(violation.rule) ?? [];
    bucket.push(violation);
    grouped.set(violation.rule, bucket);
  }

  const clean = violations.length === 0;
  const tone = !clean ? "danger" : claim.official ? "ok" : "warn";
  const standingLabel = claim.mismatch
    ? "Authority disagreement · not official"
    : claim.provisional
      ? "Provisional · no official cleanliness"
      : claim.official
        ? "No violations"
        : "Disputed standing";

  return (
    <Panel
      title="Hard violations"
      eyebrow="Rule breaches block submission"
      tone={tone}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={!clean ? "danger" : claim.official ? "ok" : "warn"}
            size="sm"
            label={!clean ? "Violations present" : standingLabel}
          />
          <span>
            {violations.length} {violations.length === 1 ? "breach" : "breaches"}
          </span>
        </span>
      }
    >
      {clean ? (
        <p className={`empty ${claim.official ? "empty--ok" : "empty--warn"}`}>
          {violationCleanSummary(claim)}
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
