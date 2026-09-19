import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelJob,
  createJob,
  createRun,
  getNetwork,
  getReport,
  getSchedule,
  healthCheck,
  listJobs,
  listRuns,
} from "./api/client";
import {
  isActiveJob,
  type NetworkResponse,
  type PlanningRun,
  type Scenario,
  type ScenarioJob,
  type ScenarioJobCreate,
  type ScheduleResponse,
  type ValidatorReportRead,
} from "./api/types";
import JobMonitor from "./components/JobMonitor";
import NetworkSummary from "./components/NetworkSummary";
import Panel from "./components/Panel";
import ResultDashboard from "./components/ResultDashboard";
import RunLibrary from "./components/RunLibrary";
import RunSummary from "./components/RunSummary";
import ScenarioLauncher from "./components/ScenarioLauncher";
import SignalLamp, { type LampTone } from "./components/SignalLamp";
import UploadPanel from "./components/UploadPanel";
import WorkflowTabs from "./components/WorkflowTabs";
import { useJobPolling } from "./hooks/useJobPolling";
import type { ActivitySelection } from "./lib/schematic";
import {
  stageAfterResultLoad,
  type WorkflowStageId,
} from "./lib/workflow";

type HealthState = "checking" | "ok" | "unavailable";

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught);
}

function jobTone(state: string): LampTone {
  switch (state) {
    case "COMPLETED":
      return "ok";
    case "QUEUED":
      return "warn";
    case "RUNNING":
    case "VALIDATING":
      return "info";
    case "FAILED":
    case "INFEASIBLE":
    case "TIMED_OUT":
    case "CANCELLED":
      return "danger";
    default:
      return "idle";
  }
}

export default function App() {
  const [activeStage, setActiveStage] = useState<WorkflowStageId>("ingest");
  const [health, setHealth] = useState<HealthState>("checking");
  const [healthError, setHealthError] = useState<string | null>(null);

  const [runs, setRuns] = useState<PlanningRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRun, setSelectedRun] = useState<PlanningRun | null>(null);
  const [network, setNetwork] = useState<NetworkResponse | null>(null);
  const [networkLoading, setNetworkLoading] = useState(false);
  const [networkError, setNetworkError] = useState<string | null>(null);

  const [jobsByRun, setJobsByRun] = useState<Record<string, ScenarioJob[]>>({});
  const [trackedJobId, setTrackedJobId] = useState<string | null>(null);
  const [launching, setLaunching] = useState<Scenario | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const [scheduleData, setScheduleData] = useState<ScheduleResponse | null>(null);
  const [reportData, setReportData] = useState<ValidatorReportRead | null>(null);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [resultError, setResultError] = useState<string | null>(null);
  const [loadedJobId, setLoadedJobId] = useState<string | null>(null);
  const [selection, setSelection] = useState<ActivitySelection | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);

  const selectedRunId = selectedRun?.id ?? null;
  const activeStageRef = useRef<WorkflowStageId>(activeStage);
  const selectedRunIdRef = useRef<string | null>(selectedRunId);
  const focusStageOnChangeRef = useRef(false);
  const lastOpenedResultKeyRef = useRef<string | null>(null);
  const resultRequestRef = useRef(0);
  activeStageRef.current = activeStage;
  selectedRunIdRef.current = selectedRunId;

  const activateStage = useCallback(
    (stage: WorkflowStageId, focusPanel = false) => {
      if (stage === activeStageRef.current) {
        focusStageOnChangeRef.current = false;
        if (focusPanel) {
          document.getElementById(`workflow-panel-${stage}`)?.focus();
        }
        return;
      }
      focusStageOnChangeRef.current = focusPanel;
      setActiveStage(stage);
    },
    [],
  );

  useEffect(() => {
    if (!focusStageOnChangeRef.current) return;
    focusStageOnChangeRef.current = false;
    document.getElementById(`workflow-panel-${activeStage}`)?.focus();
  }, [activeStage]);

  const { job: polledJobResult, error: pollError } = useJobPolling(
    selectedRunId,
    trackedJobId,
  );
  const polledJob =
    polledJobResult?.run_id === selectedRunId && polledJobResult.id === trackedJobId
      ? polledJobResult
      : null;

  const jobs = useMemo(
    () => (selectedRunId ? (jobsByRun[selectedRunId] ?? []) : []),
    [jobsByRun, selectedRunId],
  );

  const refreshHealth = useCallback(async () => {
    setHealth("checking");
    try {
      await healthCheck();
      setHealth("ok");
      setHealthError(null);
    } catch (caught) {
      setHealth("unavailable");
      setHealthError(errorMessage(caught));
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      setRuns(await listRuns());
    } catch (caught) {
      setRunsError(errorMessage(caught));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    void refreshRuns();
  }, [refreshHealth, refreshRuns]);

  const loadResults = useCallback(async (runId: string, jobId: string) => {
    const requestId = ++resultRequestRef.current;
    setResultsLoading(true);
    setResultError(null);
    try {
      const [schedule, report] = await Promise.all([
        getSchedule(runId, jobId),
        getReport(runId, jobId),
      ]);
      if (
        selectedRunIdRef.current !== runId ||
        resultRequestRef.current !== requestId
      ) {
        return;
      }
      setScheduleData(schedule);
      setReportData(report);
      setLoadedJobId(jobId);
      setSelection(null);
    } catch (caught) {
      if (
        selectedRunIdRef.current !== runId ||
        resultRequestRef.current !== requestId
      ) {
        return;
      }
      setScheduleData(null);
      setReportData(null);
      setLoadedJobId(null);
      setSelection(null);
      setResultError(errorMessage(caught));
    } finally {
      if (
        selectedRunIdRef.current === runId &&
        resultRequestRef.current === requestId
      ) {
        setResultsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!selectedRun) {
      setNetwork(null);
      setNetworkError(null);
      return;
    }
    let cancelled = false;
    setNetworkLoading(true);
    setNetworkError(null);
    setNetwork(null);
    getNetwork(selectedRun.id)
      .then((data) => {
        if (!cancelled) setNetwork(data);
      })
      .catch((caught) => {
        if (!cancelled) setNetworkError(errorMessage(caught));
      })
      .finally(() => {
        if (!cancelled) setNetworkLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRun]);

  useEffect(() => {
    resultRequestRef.current += 1;
    setScheduleData(null);
    setReportData(null);
    setLoadedJobId(null);
    setResultError(null);
    setResultsLoading(false);
    setTrackedJobId(null);
    setSelection(null);
    if (!selectedRunId) return;

    let cancelled = false;

    const newest = (list: ScenarioJob[]): ScenarioJob | null =>
      list.length === 0
        ? null
        : list.reduce((latest, job) =>
            new Date(job.submitted_at).getTime() >
            new Date(latest.submitted_at).getTime()
              ? job
              : latest,
          );

    void (async () => {
      try {
        const list = await listJobs(selectedRunId);
        if (cancelled) return;
        setJobsByRun((current) => ({ ...current, [selectedRunId]: list }));
        const active = newest(list.filter((job) => isActiveJob(job.state)));
        const completed = newest(
          list.filter((job) => job.state === "COMPLETED"),
        );
        const restore = active ?? completed;
        if (!restore) return;
        setTrackedJobId(restore.id);
        if (restore.state === "COMPLETED") {
          void loadResults(selectedRunId, restore.id);
        }
      } catch (caught) {
        if (!cancelled) setActionError(errorMessage(caught));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedRunId, loadResults]);

  useEffect(() => {
    if (!polledJob) return;
    setJobsByRun((current) => {
      const list = current[polledJob.run_id] ?? [];
      const exists = list.some((job) => job.id === polledJob.id);
      const next = exists
        ? list.map((job) => (job.id === polledJob.id ? polledJob : job))
        : [polledJob, ...list];
      return { ...current, [polledJob.run_id]: next };
    });
    if (polledJob.state === "COMPLETED" && loadedJobId !== polledJob.id) {
      void loadResults(polledJob.run_id, polledJob.id);
    }
  }, [polledJob, loadedJobId, loadResults]);

  const handleUpload = useCallback(
    async (files: File[]) => {
      const run = await createRun(files);
      setRuns((current) => [run, ...current]);
      setJobsByRun((current) => ({ ...current, [run.id]: [] }));
      setSelectedRun(run);
      activateStage("inspect", true);
      setActionError(null);
    },
    [activateStage],
  );

  const handleLaunch = useCallback(
    async (
      scenario: Scenario,
      timeLimitSeconds?: number,
      seed?: number,
    ) => {
      if (!selectedRun) {
        throw new Error("Select a planning run before dispatching a scenario.");
      }
      resultRequestRef.current += 1;
      setResultsLoading(false);
      setLaunching(scenario);
      activateStage("optimise", true);
      setActionError(null);
      try {
        const payload: ScenarioJobCreate = { scenario };
        if (timeLimitSeconds != null) {
          payload.time_limit_seconds = timeLimitSeconds;
        }
        if (seed != null) {
          payload.seed = seed;
        }
        const job = await createJob(selectedRun.id, payload);
        setJobsByRun((current) => ({
          ...current,
          [selectedRun.id]: [job, ...(current[selectedRun.id] ?? [])],
        }));
        setScheduleData(null);
        setReportData(null);
        setLoadedJobId(null);
        setResultError(null);
        setSelection(null);
        setTrackedJobId(job.id);
      } finally {
        setLaunching(null);
      }
    },
    [activateStage, selectedRun],
  );

  const handleCancel = useCallback(async (job: ScenarioJob) => {
    setCancelling(true);
    setActionError(null);
    try {
      const updated = await cancelJob(job.run_id, job.id);
      setJobsByRun((current) => {
        const list = current[updated.run_id] ?? [];
        return {
          ...current,
          [updated.run_id]: list.map((entry) =>
            entry.id === updated.id ? updated : entry,
          ),
        };
      });
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setCancelling(false);
    }
  }, []);

  const handleInspectJob = useCallback(
    (job: ScenarioJob) => {
      setTrackedJobId(job.id);
      if (job.state === "COMPLETED") {
        activateStage("validate", true);
        void loadResults(job.run_id, job.id);
        return;
      }
      // Any non-completed job (active or terminal failure) must clear the last
      // completed schedule, report and export. Otherwise a FAILED, TIMED_OUT,
      // INFEASIBLE or CANCELLED job keeps showing another job's validated
      // evidence and assurance.
      resultRequestRef.current += 1;
      setResultsLoading(false);
      activateStage("optimise", true);
      setScheduleData(null);
      setReportData(null);
      setLoadedJobId(null);
      setResultError(null);
      setSelection(null);
    },
    [activateStage, loadResults],
  );

  const handleSelectRun = useCallback(
    (run: PlanningRun) => {
      setSelectedRun(run);
      activateStage("inspect", true);
    },
    [activateStage],
  );

  const handleSelect = useCallback((next: ActivitySelection) => {
    setSelection(next);
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelection(null);
  }, []);

  const resultReady =
    scheduleData != null &&
    reportData != null &&
    selectedRun != null &&
    network != null &&
    scheduleData.run_id === selectedRun.id &&
    scheduleData.job_id === loadedJobId;

  const resultKey = resultReady && scheduleData
    ? `${scheduleData.run_id}:${scheduleData.job_id}`
    : null;

  useEffect(() => {
    const nextStage = stageAfterResultLoad(
      activeStage,
      lastOpenedResultKeyRef.current,
      resultKey,
    );
    if (resultKey != null) {
      lastOpenedResultKeyRef.current = resultKey;
    }
    if (nextStage !== activeStage) {
      activateStage(nextStage, true);
    }
  }, [activateStage, activeStage, resultKey]);

  const workflowReadiness = {
    hasRun: selectedRun != null,
    hasNetwork: network != null,
    hasJob: trackedJobId != null,
    hasResults: resultReady,
  };

  const resolvedReport = reportData
    ? {
        ...reportData.report,
        ready_for_submission: reportData.ready_for_submission,
      }
    : null;

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__brand">
          <span className="masthead__mark" aria-hidden="true">
            RAO
          </span>
          <div>
            <h1>Rail Access Optimisation</h1>
            <p>Judge workflow control board · Scenario A/B/C</p>
          </div>
        </div>
        <div className="masthead__status" role="status" aria-live="polite">
          <span className="masthead__stat">
            <SignalLamp
              tone={
                health === "ok" ? "ok" : health === "checking" ? "warn" : "danger"
              }
              size="sm"
              pulse={health === "checking"}
              label={`Backend ${health}`}
            />
            <span>
              backend {health}
              {healthError ? `: ${healthError}` : ""}
            </span>
          </span>
          <span className="masthead__stat">
            <SignalLamp tone="idle" size="sm" label="Runs loaded" />
            <span>{runs.length} runs loaded</span>
          </span>
          {selectedRun ? (
            <span className="masthead__stat">
              <SignalLamp
                tone={polledJob ? jobTone(polledJob.state) : "idle"}
                size="sm"
                pulse={polledJob ? isActiveJob(polledJob.state) : false}
                label={polledJob ? `Job ${polledJob.state}` : "No tracked job"}
              />
              <span>
                run {selectedRun.id.slice(0, 8)}
                {polledJob ? ` · ${polledJob.scenario} ${polledJob.state}` : ""}
              </span>
            </span>
          ) : null}
        </div>
      </header>

      {actionError ? (
        <div className="notice notice--danger notice--global" role="alert">
          <span className="notice__title">Action failed</span>
          <p>{actionError}</p>
          <button
            type="button"
            className="btn btn--tiny"
            onClick={() => setActionError(null)}
          >
            Dismiss
          </button>
        </div>
      ) : null}

      <WorkflowTabs
        activeStage={activeStage}
        readiness={workflowReadiness}
        onChange={setActiveStage}
      />

      <main className="workflow-content">
        <section
          id="workflow-panel-ingest"
          role="tabpanel"
          aria-labelledby="workflow-tab-ingest"
          tabIndex={-1}
          hidden={activeStage !== "ingest"}
          className="workflow-panel"
        >
          <div className="board board--intake">
            <div className="board__column">
              <UploadPanel onUpload={handleUpload} />
            </div>
            <div className="board__column">
              <RunLibrary
                runs={runs}
                selectedRunId={selectedRunId}
                loading={runsLoading}
                error={runsError}
                onSelect={handleSelectRun}
                onRefresh={() => void refreshRuns()}
              />
            </div>
          </div>
        </section>

        <section
          id="workflow-panel-inspect"
          role="tabpanel"
          aria-labelledby="workflow-tab-inspect"
          tabIndex={-1}
          hidden={activeStage !== "inspect"}
          className="workflow-panel"
        >
          {selectedRun ? (
            <div className="dashboard">
              <RunSummary run={selectedRun} />
              {network ? (
                <NetworkSummary network={network} />
              ) : (
                <Panel title="Network summary" eyebrow="Stage 2 · Inspect · /network">
                  {networkError ? (
                    <div className="notice notice--danger" role="alert">
                      <span className="notice__title">Could not load network</span>
                      <p>{networkError}</p>
                    </div>
                  ) : (
                    <p className="empty" role="status" aria-live="polite">
                      {networkLoading ? "Loading network topology…" : "No network loaded."}
                    </p>
                  )}
                </Panel>
              )}
            </div>
          ) : null}
        </section>

        <section
          id="workflow-panel-optimise"
          role="tabpanel"
          aria-labelledby="workflow-tab-optimise"
          tabIndex={-1}
          hidden={activeStage !== "optimise"}
          className="workflow-panel"
        >
          {selectedRun ? (
            <div className="dashboard">
              <ScenarioLauncher
                disabled={!network}
                launching={launching}
                jobs={jobs}
                selectedJobId={trackedJobId}
                onLaunch={handleLaunch}
                onInspectJob={handleInspectJob}
              />
              <JobMonitor
                job={polledJob}
                pollError={pollError}
                cancelling={cancelling}
                onCancel={handleCancel}
              />
            </div>
          ) : null}
        </section>

        <section
          id="workflow-panel-validate"
          role="tabpanel"
          aria-labelledby="workflow-tab-validate"
          tabIndex={-1}
          hidden={activeStage !== "validate"}
          className="workflow-panel"
        >
          {resultsLoading ? (
            <Panel title="Validation console" eyebrow="Stage 4 · Loading evidence">
              <p className="empty" role="status" aria-live="polite">
                Fetching the schedule, physical witness and validator report…
              </p>
            </Panel>
          ) : null}

          {resultError && !resultsLoading ? (
            <Panel title="Validation console" eyebrow="Stage 4 · Unavailable" tone="danger">
              <div className="notice notice--danger" role="alert">
                <span className="notice__title">Results unavailable</span>
                <p>{resultError}</p>
              </div>
            </Panel>
          ) : null}

          {!resultsLoading && !resultError && !resultReady ? (
            <Panel title="Validation console" eyebrow="Stage 4 · Awaiting result">
              <p className="empty" role="status" aria-live="polite">
                {polledJob
                  ? `Scenario ${polledJob.scenario} is ${polledJob.state.toLowerCase()}. Validation evidence will appear when the job completes.`
                  : "Select a scenario job to load its validation evidence."}
              </p>
            </Panel>
          ) : null}

          {resultReady && scheduleData && resolvedReport && selectedRun && network ? (
            <ResultDashboard
              section="validate"
              runId={selectedRun.id}
              jobId={scheduleData.job_id}
              scenario={scheduleData.scenario}
              schedule={scheduleData}
              report={resolvedReport}
              network={network}
              selection={selection}
              onSelect={handleSelect}
              onClearSelection={handleClearSelection}
            />
          ) : null}
        </section>

        <section
          id="workflow-panel-explain"
          role="tabpanel"
          aria-labelledby="workflow-tab-explain"
          tabIndex={-1}
          hidden={activeStage !== "explain"}
          className="workflow-panel"
        >
          {resultReady && scheduleData && resolvedReport && selectedRun && network ? (
            <ResultDashboard
              section="explain"
              runId={selectedRun.id}
              jobId={scheduleData.job_id}
              scenario={scheduleData.scenario}
              schedule={scheduleData}
              report={resolvedReport}
              network={network}
              selection={selection}
              onSelect={handleSelect}
              onClearSelection={handleClearSelection}
            />
          ) : null}
        </section>

        <section
          id="workflow-panel-export"
          role="tabpanel"
          aria-labelledby="workflow-tab-export"
          tabIndex={-1}
          hidden={activeStage !== "export"}
          className="workflow-panel"
        >
          {resultReady && scheduleData && resolvedReport && selectedRun && network ? (
            <ResultDashboard
              section="export"
              runId={selectedRun.id}
              jobId={scheduleData.job_id}
              scenario={scheduleData.scenario}
              schedule={scheduleData}
              report={resolvedReport}
              network={network}
              selection={selection}
              onSelect={handleSelect}
              onClearSelection={handleClearSelection}
            />
          ) : null}
        </section>
      </main>

      <footer className="footer">
        <span>
          UI displays server-computed schedules and scores only; no scheduling logic
          runs in the browser.
        </span>
        <span>
          Scenarios A/B/C are distinct answer keys. Downloads are gated by the
          validator.
        </span>
      </footer>
    </div>
  );
}
