export type AssuranceLayerState = "pass" | "fail" | "unavailable";
export type OverallAssuranceStatus =
  | "OFFICIALLY VALIDATED"
  | "PROVISIONAL"
  | "NOT VALIDATED";

export interface AssuranceInput {
  authority: string;
  validatorSource?: string | null;
  feasible: boolean;
  workloadComplete: boolean;
  physical: AssuranceLayerState;
}

export interface AssuranceOutcome {
  status: OverallAssuranceStatus;
  physical: AssuranceLayerState;
  fallback: AssuranceLayerState;
  official: AssuranceLayerState;
  failingLayers: string[];
  authorityMismatch: boolean;
}

// Derive the overall submission status from the three independent layers. The
// report's claimed authority is only trusted when it agrees with the recorded
// validator source. Official validation is never inferred from the fallback, and
// the fallback is never presented as authoritative acceptance.
export function deriveAssurance(input: AssuranceInput): AssuranceOutcome {
  const source = input.validatorSource ?? input.authority;
  const authorityMismatch = source !== input.authority;
  const validatorPassed = input.feasible && input.workloadComplete;

  const official: AssuranceLayerState =
    !authorityMismatch && input.authority === "official"
      ? validatorPassed
        ? "pass"
        : "fail"
      : "unavailable";
  const fallback: AssuranceLayerState =
    !authorityMismatch && input.authority === "fallback"
      ? validatorPassed
        ? "pass"
        : "fail"
      : "unavailable";

  const failingLayers: string[] = [];
  const notePhysical = () => {
    if (input.physical !== "pass") {
      failingLayers.push(
        input.physical === "unavailable"
          ? "physical schedule checks (not recorded)"
          : "physical schedule checks",
      );
    }
  };
  // A validator layer that passed is never named as failing. When the physical
  // checks are the only unmet layer, the verdict names physical alone even
  // though the overall status is NOT VALIDATED.
  const noteValidator = () => {
    if (input.authority === "official" && official !== "pass") {
      failingLayers.push("official validation");
    } else if (input.authority === "fallback" && fallback !== "pass") {
      failingLayers.push("fallback schema validation");
    }
  };

  let status: OverallAssuranceStatus;
  if (authorityMismatch) {
    status = "NOT VALIDATED";
    notePhysical();
    failingLayers.push(
      `validator authority disagreement (${input.authority} vs ${source})`,
    );
  } else if (official === "pass" && input.physical === "pass") {
    status = "OFFICIALLY VALIDATED";
  } else if (fallback === "pass" && input.physical === "pass") {
    status = "PROVISIONAL";
  } else if (input.authority !== "official" && input.authority !== "fallback") {
    status = "NOT VALIDATED";
    notePhysical();
    failingLayers.push(`unrecognised validation authority (${input.authority})`);
  } else {
    status = "NOT VALIDATED";
    notePhysical();
    noteValidator();
  }

  return {
    status,
    physical: input.physical,
    fallback,
    official,
    failingLayers,
    authorityMismatch,
  };
}

export function checkDetailText(
  detail: string | Record<string, unknown>,
): string {
  if (typeof detail === "string") return detail;
  const reason = detail.reason;
  if (typeof reason === "string" && reason) return reason;

  let foundIssueCollection = false;
  for (const [key, label] of [
    ["violations", "issue(s)"],
    ["hard_violations", "hard violation(s)"],
    ["soft_excess", "soft excess issue(s)"],
  ] as const) {
    const value = detail[key];
    if (Array.isArray(value)) {
      foundIssueCollection = true;
      if (value.length > 0) return `${value.length} ${label}`;
    }
  }
  if (
    typeof detail.soft_excess_total === "number" &&
    detail.soft_excess_total > 0
  ) {
    return `soft excess ${detail.soft_excess_total}`;
  }
  if (foundIssueCollection) return "none";
  if (typeof detail.activities_without_physical_night === "number") {
    return `${detail.activities_without_physical_night} row(s) without a slot`;
  }
  const text = JSON.stringify(detail);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}
