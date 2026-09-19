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
