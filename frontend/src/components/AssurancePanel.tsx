import type { ReactNode } from "react";

import type {
  PhysicalCheckReport,
  ValidatorReport,
} from "../api/types";
import { checkDetailText } from "../lib/assurance";
import Panel from "./Panel";
import SignalLamp, { type LampTone } from "./SignalLamp";

interface AssurancePanelProps {
  report: ValidatorReport;
  physicalChecks?: PhysicalCheckReport | null;
}

type LayerState = "pass" | "fail" | "unavailable";
type OverallStatus = "OFFICIALLY VALIDATED" | "PROVISIONAL" | "NOT VALIDATED";

const STATE_LABELS: Record<LayerState, string> = {
  pass: "PASS",
  fail: "FAIL",
  unavailable: "NOT AVAILABLE",
};

function lampTone(state: LayerState): LampTone {
  if (state === "pass") return "ok";
  if (state === "fail") return "danger";
  return "idle";
}

function CheckMark({ passed }: { passed: boolean }) {
  return (
    <span
      className={`assurance__mark assurance__mark--${passed ? "pass" : "fail"}`}
      role="img"
      aria-label={passed ? "passed" : "failed"}
    >
      {passed ? "✓" : "✕"}
    </span>
  );
}

function LayerRow({
  title,
  subtitle,
  state,
  stateLabel,
  detail,
  children,
}: {
  title: string;
  subtitle: string;
  state: LayerState;
  stateLabel?: string;
  detail: string;
  children?: ReactNode;
}) {
  return (
    <li className={`assurance__row assurance__row--${state}`}>
      <SignalLamp tone={lampTone(state)} label={`${title} ${state}`} />
      <div className="assurance__identity">
        <span className="assurance__title">{title}</span>
        <span className="assurance__sub">{subtitle}</span>
      </div>
      <span className={`assurance__state assurance__state--${state}`}>
        {stateLabel ?? STATE_LABELS[state]}
      </span>
      <p className="assurance__detail">{detail}</p>
      {children}
    </li>
  );
}

export default function AssurancePanel({
  report,
  physicalChecks,
}: AssurancePanelProps) {
  const officialAuthority = report.authority === "official";
  const fallbackAuthority = report.authority === "fallback";

  const validatorPassed = report.feasible && report.workload_complete;

  const physicalState: LayerState =
    physicalChecks == null ? "unavailable" : physicalChecks.passed ? "pass" : "fail";
  const fallbackState: LayerState = fallbackAuthority
    ? validatorPassed
      ? "pass"
      : "fail"
    : "unavailable";
  const officialState: LayerState = officialAuthority
    ? validatorPassed
      ? "pass"
      : "fail"
    : "unavailable";

  let status: OverallStatus;
  const failingLayers: string[] = [];
  if (officialAuthority) {
    if (physicalState === "pass" && validatorPassed) {
      status = "OFFICIALLY VALIDATED";
    } else {
      status = "NOT VALIDATED";
      if (physicalState !== "pass") {
        failingLayers.push(
          physicalState === "unavailable"
            ? "physical schedule checks (not recorded)"
            : "physical schedule checks",
        );
      }
      if (!validatorPassed) failingLayers.push("official validation");
    }
  } else if (fallbackAuthority && physicalState === "pass" && validatorPassed) {
    status = "PROVISIONAL";
  } else {
    status = "NOT VALIDATED";
    if (physicalState !== "pass") {
      failingLayers.push(
        physicalState === "unavailable"
          ? "physical schedule checks (not recorded)"
          : "physical schedule checks",
      );
    }
    if (!(fallbackAuthority && validatorPassed)) {
      failingLayers.push("fallback schema validation");
    }
  }

  const verdictTone: "ok" | "warn" | "danger" =
    status === "OFFICIALLY VALIDATED"
      ? "ok"
      : status === "PROVISIONAL"
        ? "warn"
        : "danger";

  const verdictNote =
    status === "OFFICIALLY VALIDATED"
      ? "The official validator accepted feasibility and full workload for this submission."
      : status === "PROVISIONAL"
        ? "The internal physical checks and the fallback validator both pass, but no official validator was configured. Treat this submission as provisional."
        : `Not all assurance layers pass. Failing layer${failingLayers.length === 1 ? "" : "s"}: ${failingLayers.join(", ")}.`;

  const physicalFailed = physicalChecks
    ? physicalChecks.checks.filter((check) => !check.passed).length
    : 0;
  const physicalDetail =
    physicalState === "unavailable"
      ? "Physical schedule checks were not recorded for this run, so this internal layer cannot be confirmed. Older runs predate the witness check."
      : physicalState === "pass"
        ? `All ${physicalChecks?.checks.length ?? 0} named check${
            (physicalChecks?.checks.length ?? 0) === 1 ? "" : "s"
          } passed on the persisted physical slots.`
        : `${physicalFailed} of ${physicalChecks?.checks.length ?? 0} named check${
            (physicalChecks?.checks.length ?? 0) === 1 ? "" : "s"
          } failed on the persisted physical slots.`;

  const fallbackDetail =
    fallbackState === "unavailable"
      ? "Not used for this run because the official validator was the recorded authority."
      : fallbackState === "pass"
        ? "The exported CSVs conform to the current interpretation of the published rules. This interpretation is provisional and is not the official validator."
        : "The exported CSVs breach the current interpretation of the published rules.";

  const officialDetail =
    officialState === "unavailable"
      ? "Not available: no official validator was configured for this run, so official acceptance cannot be claimed."
      : officialState === "pass"
        ? "The official validator accepted feasibility and full workload."
        : "The official validator rejected this submission on feasibility or workload completeness.";

  return (
    <Panel
      title="Validation assurance"
      eyebrow="Three independent layers · derived status"
      tone={verdictTone}
      actions={
        <span className={`gate-banner gate-banner--${verdictTone}`}>
          <SignalLamp
            tone={verdictTone}
            pulse={status === "PROVISIONAL"}
            label={`Overall status ${status}`}
          />
          <span>{status}</span>
        </span>
      }
    >
      <p className="assurance__summary">
        Each layer proves something different. One is never presented as another.
      </p>

      <ul className="assurance__rows" aria-label="Validation assurance layers">
        <LayerRow
          title="Physical schedule checks"
          subtitle="Internal witness · solver's persisted physical slots"
          state={physicalState}
          detail={physicalDetail}
        >
          {physicalChecks && physicalChecks.checks.length > 0 ? (
            <ul className="assurance__checks" aria-label="Physical check results">
              {physicalChecks.checks.map((check) => (
                <li
                  key={check.name}
                  className={`assurance__check assurance__check--${check.passed ? "pass" : "fail"}`}
                >
                  <CheckMark passed={check.passed} />
                  <span className="assurance__check-name">{check.name}</span>
                  <span className="assurance__check-detail">
                    {checkDetailText(check.detail)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </LayerRow>

        <LayerRow
          title="Fallback schema validation"
          subtitle='Authority "fallback" · provisional interpretation'
          state={fallbackState}
          stateLabel={fallbackState === "pass" ? "PROVISIONAL PASS" : undefined}
          detail={fallbackDetail}
        />

        <LayerRow
          title="Official validation"
          subtitle='Authority "official" · final acceptance'
          state={officialState}
          detail={officialDetail}
        />
      </ul>

      <div className={`assurance__verdict assurance__verdict--${verdictTone}`}>
        <span className="assurance__verdict-label">Overall submission status</span>
        <span className="assurance__verdict-value">{status}</span>
        <p className="assurance__verdict-note">{verdictNote}</p>
      </div>
    </Panel>
  );
}
