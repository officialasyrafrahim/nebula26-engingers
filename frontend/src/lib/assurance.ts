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

export type AuthorityStanding = "official" | "provisional" | "disputed";

export interface AuthorityClaim {
  authority: string;
  source: string;
  mismatch: boolean;
  official: boolean;
  provisional: boolean;
  standing: AuthorityStanding;
}

// Resolve what the recorded validator is allowed to claim from the report's
// stated authority and the source that actually recorded it. A disagreement, or
// an authority the app does not recognise, can claim neither official nor
// fallback standing. Components must read this helper rather than trusting the
// `authority` field alone.
export function deriveAuthorityClaim(
  authority: string,
  validatorSource?: string | null,
): AuthorityClaim {
  const source = validatorSource ?? authority;
  const mismatch = source !== authority;
  if (mismatch) {
    return {
      authority,
      source,
      mismatch: true,
      official: false,
      provisional: false,
      standing: "disputed",
    };
  }
  if (authority === "official") {
    return {
      authority,
      source,
      mismatch: false,
      official: true,
      provisional: false,
      standing: "official",
    };
  }
  if (authority === "fallback") {
    return {
      authority,
      source,
      mismatch: false,
      official: false,
      provisional: true,
      standing: "provisional",
    };
  }
  return {
    authority,
    source,
    mismatch: false,
    official: false,
    provisional: false,
    standing: "disputed",
  };
}

// Copy for the hard-violations panel when nothing is flagged. A fallback or
// disputed standing must never be worded as official cleanliness.
export function violationCleanSummary(claim: AuthorityClaim): string {
  if (claim.mismatch) {
    return "The validator authority and the recorded source disagree, so no clean status can be claimed. Do not treat this as official cleanliness.";
  }
  if (claim.provisional) {
    return "The fallback validator found no hard-rule violations. This is provisional fallback interpretation, not official acceptance or physical proof.";
  }
  if (claim.official) {
    return "The official validator found no hard-rule violations. The schedule is clean under the official authority.";
  }
  return "No hard-rule violations reported, but the validator standing is unrecognised or disputed. Do not treat this as official cleanliness.";
}

// Derive the overall submission status from the three independent layers. The
// report's claimed authority is only trusted when it agrees with the recorded
// validator source. Official validation is never inferred from the fallback, and
// the fallback is never presented as authoritative acceptance.
export function deriveAssurance(input: AssuranceInput): AssuranceOutcome {
  const claim = deriveAuthorityClaim(input.authority, input.validatorSource);
  const authorityMismatch = claim.mismatch;
  const validatorPassed = input.feasible && input.workloadComplete;

  const official: AssuranceLayerState = claim.official
    ? validatorPassed
      ? "pass"
      : "fail"
    : "unavailable";
  const fallback: AssuranceLayerState = claim.provisional
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
      `validator authority disagreement (${input.authority} vs ${claim.source})`,
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
