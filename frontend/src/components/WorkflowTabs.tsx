import { useRef, type KeyboardEvent } from "react";

import {
  isWorkflowStageAvailable,
  workflowStageState,
  WORKFLOW_STAGES,
  type WorkflowReadiness,
  type WorkflowStageId,
} from "../lib/workflow";

interface WorkflowTabsProps {
  activeStage: WorkflowStageId;
  readiness: WorkflowReadiness;
  onChange: (stage: WorkflowStageId) => void;
}

const STATE_LABELS = {
  active: "Viewing",
  complete: "Complete",
  ready: "Ready",
  locked: "Locked",
} as const;

export default function WorkflowTabs({
  activeStage,
  readiness,
  onChange,
}: WorkflowTabsProps) {
  const tabRefs = useRef<Partial<Record<WorkflowStageId, HTMLButtonElement | null>>>({});

  const moveFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    target: "previous" | "next" | "first" | "last",
  ) => {
    const available = WORKFLOW_STAGES.filter((stage) =>
      isWorkflowStageAvailable(stage.id, readiness),
    );
    const currentIndex = available.findIndex((stage) => stage.id === activeStage);
    if (currentIndex < 0) return;

    let nextIndex = currentIndex;
    if (target === "previous") {
      nextIndex = (currentIndex - 1 + available.length) % available.length;
    } else if (target === "next") {
      nextIndex = (currentIndex + 1) % available.length;
    } else if (target === "first") {
      nextIndex = 0;
    } else {
      nextIndex = available.length - 1;
    }

    event.preventDefault();
    const nextStage = available[nextIndex].id;
    onChange(nextStage);
    tabRefs.current[nextStage]?.focus();
  };

  return (
    <nav className="workflow-nav" aria-label="Planning workflow">
      <div className="workflow-nav__heading">
        <span className="workflow-nav__eyebrow">Planning workflow</span>
        <strong>{WORKFLOW_STAGES.find((stage) => stage.id === activeStage)?.label}</strong>
      </div>
      <div
        className="workflow-tabs"
        role="tablist"
        aria-label="Planning stages"
        aria-orientation="horizontal"
      >
        {WORKFLOW_STAGES.map((stage) => {
          const available = isWorkflowStageAvailable(stage.id, readiness);
          const state = workflowStageState(stage.id, activeStage, readiness);
          return (
            <button
              key={stage.id}
              ref={(element) => {
                tabRefs.current[stage.id] = element;
              }}
              id={`workflow-tab-${stage.id}`}
              type="button"
              role="tab"
              className={`workflow-tab workflow-tab--${state}`}
              aria-selected={activeStage === stage.id}
              aria-controls={`workflow-panel-${stage.id}`}
              aria-disabled={!available}
              tabIndex={activeStage === stage.id ? 0 : -1}
              disabled={!available}
              title={available ? stage.description : `${stage.label} is not available yet`}
              onClick={() => onChange(stage.id)}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") moveFocus(event, "previous");
                if (event.key === "ArrowRight") moveFocus(event, "next");
                if (event.key === "Home") moveFocus(event, "first");
                if (event.key === "End") moveFocus(event, "last");
              }}
            >
              <span className="workflow-tab__number">{stage.number}</span>
              <span className="workflow-tab__body">
                <span className="workflow-tab__label">{stage.label}</span>
                <span className="workflow-tab__description">{stage.description}</span>
              </span>
              <span className="workflow-tab__state">
                <span className="workflow-tab__signal" aria-hidden="true" />
                {STATE_LABELS[state]}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
