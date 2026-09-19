import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  isWorkflowStageAvailable,
  stageAfterResultLoad,
  WORKFLOW_STAGES,
  workflowStageState,
  type WorkflowReadiness,
} from "../src/lib/workflow.ts";

describe("workflow stage availability", () => {
  it("keeps the seven stages in judge workflow order", () => {
    assert.deepEqual(
      WORKFLOW_STAGES.map((stage) => stage.id),
      ["ingest", "inspect", "optimise", "validate", "explain", "calendar", "export"],
    );
  });

  it("locks downstream stages before a run is ingested", () => {
    const readiness: WorkflowReadiness = {
      hasRun: false,
      hasNetwork: false,
      hasJob: false,
      hasResults: false,
    };

    assert.equal(isWorkflowStageAvailable("ingest", readiness), true);
    assert.equal(isWorkflowStageAvailable("inspect", readiness), false);
    assert.equal(isWorkflowStageAvailable("optimise", readiness), false);
    assert.equal(isWorkflowStageAvailable("validate", readiness), false);
    assert.equal(isWorkflowStageAvailable("explain", readiness), false);
    assert.equal(isWorkflowStageAvailable("export", readiness), false);
  });

  it("opens validation for a tracked job and results for a completed job", () => {
    const running: WorkflowReadiness = {
      hasRun: true,
      hasNetwork: true,
      hasJob: true,
      hasResults: false,
    };
    const completed = { ...running, hasResults: true };

    assert.equal(isWorkflowStageAvailable("validate", running), true);
    assert.equal(isWorkflowStageAvailable("explain", running), false);
    assert.equal(isWorkflowStageAvailable("explain", completed), true);
    assert.equal(isWorkflowStageAvailable("export", completed), true);
  });
});

describe("result-driven stage transitions", () => {
  it("opens validation only for a newly loaded result", () => {
    assert.equal(stageAfterResultLoad("optimise", null, "run-1:job-1"), "validate");
    assert.equal(
      stageAfterResultLoad("optimise", "run-1:job-1", "run-1:job-1"),
      "optimise",
    );
    assert.equal(stageAfterResultLoad("inspect", "run-1:job-1", null), "inspect");
    assert.equal(
      stageAfterResultLoad("inspect", "run-1:job-1", "run-1:job-2"),
      "validate",
    );
  });
});

describe("workflow stage state", () => {
  it("marks satisfied earlier stages complete", () => {
    const readiness: WorkflowReadiness = {
      hasRun: true,
      hasNetwork: true,
      hasJob: true,
      hasResults: true,
    };

    assert.equal(workflowStageState("ingest", "validate", readiness), "complete");
    assert.equal(workflowStageState("inspect", "validate", readiness), "complete");
    assert.equal(workflowStageState("optimise", "validate", readiness), "complete");
    assert.equal(workflowStageState("validate", "validate", readiness), "active");
    assert.equal(workflowStageState("explain", "validate", readiness), "ready");
  });
});
