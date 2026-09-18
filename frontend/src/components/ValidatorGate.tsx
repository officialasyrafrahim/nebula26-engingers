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
  const violations = report.hard_violations.length;
  return (
    <Panel
      title="Validator gate"
      eyebrow={`Stage 5 · Explain · authority ${report.authority}`}
      tone={ready ? "ok" : "danger"}
      actions={
        <span className={`gate-banner gate-banner--${ready ? "open" : "blocked"}`}>
          <SignalLamp
            tone={ready ? "ok" : "danger"}
            pulse={ready}
            label={ready ? "Ready for submission" : "Submission blocked"}
          />
          <span>{ready ? "READY" : "BLOCKED"}</span>
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
          detail={ready ? "Export enabled" : "Export withheld until gate passes"}
        />
      </ul>

      <div className="gate-meta">
        <span>
          Validation authority: <strong>{report.authority}</strong>
        </span>
        {report.authority === "fallback" ? (
          <span className="gate-meta__provisional">
            Provisional: the official validator was not configured, so the bundled
            fallback is the executable authority for this run.
          </span>
        ) : null}
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
