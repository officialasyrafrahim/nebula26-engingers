export const WORKFLOW_STAGES = [
  {
    id: "ingest",
    number: "01",
    label: "Ingest",
    description: "Files and saved runs",
  },
  {
    id: "inspect",
    number: "02",
    label: "Inspect",
    description: "Parse and topology",
  },
  {
    id: "optimise",
    number: "03",
    label: "Optimise",
    description: "Scenario and solver",
  },
  {
    id: "validate",
    number: "04",
    label: "Validate",
    description: "Assurance and score",
  },
  {
    id: "explain",
    number: "05",
    label: "Explain",
    description: "Schedule evidence",
  },
  {
    id: "calendar",
    number: "06",
    label: "Calendar",
    description: "Physical possessions",
  },
  {
    id: "export",
    number: "07",
    label: "Export",
    description: "Submission bundle",
  },
] as const;

export type WorkflowStageId = (typeof WORKFLOW_STAGES)[number]["id"];
export type WorkflowStageState = "active" | "complete" | "ready" | "locked";

export interface WorkflowReadiness {
  hasRun: boolean;
  hasNetwork: boolean;
  hasJob: boolean;
  hasResults: boolean;
}

export function isWorkflowStageAvailable(
  stage: WorkflowStageId,
  readiness: WorkflowReadiness,
): boolean {
  switch (stage) {
    case "ingest":
      return true;
    case "inspect":
      return readiness.hasRun;
    case "optimise":
      return readiness.hasNetwork;
    case "validate":
      return readiness.hasJob;
    case "explain":
    case "calendar":
    case "export":
      return readiness.hasResults;
  }
}

export function workflowStageState(
  stage: WorkflowStageId,
  activeStage: WorkflowStageId,
  readiness: WorkflowReadiness,
): WorkflowStageState {
  if (stage === activeStage) return "active";
  if (!isWorkflowStageAvailable(stage, readiness)) return "locked";

  const complete =
    (stage === "ingest" && readiness.hasRun) ||
    (stage === "inspect" && readiness.hasNetwork) ||
    (stage === "optimise" && readiness.hasResults) ||
    (stage === "validate" && readiness.hasResults);

  return complete ? "complete" : "ready";
}

export function stageAfterResultLoad(
  activeStage: WorkflowStageId,
  lastResultKey: string | null,
  resultKey: string | null,
): WorkflowStageId {
  return resultKey != null && resultKey !== lastResultKey ? "validate" : activeStage;
}
