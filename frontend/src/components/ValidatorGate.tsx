import type { ValidatorReport } from "../api/types";
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
  const ready = report.ready_for_submission;
  const provisional = report.authority === "fallback";
  const violations = report.hard_violations.length;
  const tone = ready ? (provisional ? "warn" : "ok") : "danger";
  const banner = ready ? (provisional ? "provisional" : "open") : "blocked";
  const bannerLabel = ready ? (provisional ? "Provisional" : "Ready for submission") : "Submission blocked";
  return (
    <Panel
      title="Validator gate"
      eyebrow={`Stage 4 · Validate · authority ${report.authority}`}
      tone={tone}
      actions={
        <span className={`gate-banner gate-banner--${banner}`}>
          <SignalLamp
            tone={ready ? (provisional ? "warn" : "ok") : "danger"}
            pulse={ready && !provisional}
            label={bannerLabel}
          />
          <span>{ready ? (provisional ? "PROVISIONAL" : "READY") : "BLOCKED"}</span>
        </span>
      }
    >
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
            ready
              ? provisional
                ? "Export enabled · provisional authority"
                : "Export enabled · official authority"
              : "Export withheld until gate passes"
          }
        />
      </ul>

      <div className="gate-meta">
        <span>
          Validation authority: <strong>{report.authority}</strong>
        </span>
        {provisional ? (
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
