import type { ValidatorReport } from "../api/types";
import { deriveAuthorityClaim } from "../lib/assurance";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ValidatorGateProps {
  report: ValidatorReport;
}

function GateCell({
  label,
  passed,
  detail,
}: {
  label: string;
  passed: boolean;
  detail: string;
}) {
  return (
    <li className={`gate${passed ? " gate--pass" : " gate--fail"}`}>
      <SignalLamp
        tone={passed ? "ok" : "danger"}
        label={`${label} ${passed ? "passed" : "blocked"}`}
      />
      <span className="gate__label">{label}</span>
      <span className="gate__detail">{detail}</span>
    </li>
  );
}

export default function ValidatorGate({ report }: ValidatorGateProps) {
  const claim = deriveAuthorityClaim(report.authority, report.validator_source);
  const disputed = claim.mismatch;
  const provisional = claim.provisional;
  const ready = report.ready_for_submission && !disputed;
  const violations = report.hard_violations.length;
  const tone = disputed ? "danger" : ready ? (provisional ? "warn" : "ok") : "danger";
  const banner = disputed ? "blocked" : ready ? (provisional ? "provisional" : "open") : "blocked";
  const bannerLabel = disputed
    ? "Validator authority disagreement"
    : ready
      ? provisional
        ? "Provisional"
        : "Ready for submission"
      : "Submission blocked";
  const bannerText = disputed
    ? "DISPUTED"
    : ready
      ? provisional
        ? "PROVISIONAL"
        : "READY"
      : "BLOCKED";
  return (
    <Panel
      title="Validator gate"
      eyebrow={`Stage 4 · Validate · authority ${report.authority}`}
      tone={tone}
      actions={
        <span className={`gate-banner gate-banner--${banner}`}>
          <SignalLamp
            tone={tone}
            pulse={ready && !provisional}
            label={bannerLabel}
          />
          <span>{bannerText}</span>
        </span>
      }
    >
      {disputed ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Validator authority disagreement</span>
          <p>
            The report claims authority &quot;{report.authority}&quot; but was
            recorded by &quot;{report.validator_source}&quot;. The gate cannot be
            treated as official, so submission is withheld.
          </p>
        </div>
      ) : null}

      <ul className="gates" aria-label="Submission gate checks">
        <GateCell
          label="Feasible"
          passed={report.feasible}
          detail={
            report.feasible
              ? "No hard-rule violations"
              : `${violations} hard violation${violations === 1 ? "" : "s"}`
          }
        />
        <GateCell
          label="Workload complete"
          passed={report.workload_complete}
          detail={
            report.workload_complete
              ? "Every activity fully accounted for"
              : "Workload is not fully scheduled"
          }
        />
        <GateCell
          label="Ready for submission"
          passed={ready}
          detail={
            disputed
              ? "Withheld · validator authority disagreement"
              : ready
                ? provisional
                  ? "Export enabled · provisional authority"
                  : "Export enabled · official authority"
                : "Export withheld until gate passes"
          }
        />
      </ul>

      <div className="gate-meta">
        <span>
          Validation authority: <strong>{report.authority}</strong> · recorded by{" "}
          <strong>{report.validator_source}</strong>
        </span>
        {disputed ? (
          <span className="gate-meta__provisional">
            Disputed: the claimed authority and the recorded source disagree, so no
            official gate status can be claimed.
          </span>
        ) : provisional ? (
          <span className="gate-meta__provisional">
            Provisional: the official validator was not configured, so the bundled
            fallback interpreted the published rules. Fallback success is not
            authoritative acceptance.
          </span>
        ) : (
          <span>
            Official: the recorded result comes from the configured official
            validator.
          </span>
        )}
      </div>

      {report.parse_errors && report.parse_errors.length > 0 ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Submission parse errors</span>
          <ul className="notice__list">
            {report.parse_errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}
