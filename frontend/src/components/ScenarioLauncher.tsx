import { useState } from "react";

import { ApiError } from "../api/client";
import { isActiveJob, type ScenarioJob, type Scenario } from "../api/types";
import { SCENARIOS, scenarioSpec } from "../lib/scenarios";
import { formatDateTime } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ScenarioLauncherProps {
  disabled: boolean;
  launching: Scenario | null;
  jobs: ScenarioJob[];
  selectedJobId: string | null;
  onLaunch: (
    scenario: Scenario,
    timeLimitSeconds?: number,
    seed?: number,
  ) => Promise<void>;
  onInspectJob: (job: ScenarioJob) => void;
}

function stateTone(state: ScenarioJob["state"]): "ok" | "warn" | "danger" | "info" | "idle" {
  switch (state) {
    case "COMPLETED":
      return "ok";
    case "RUNNING":
    case "VALIDATING":
      return "info";
    case "QUEUED":
      return "warn";
    case "FAILED":
    case "INFEASIBLE":
    case "TIMED_OUT":
      return "danger";
    default:
      return "idle";
  }
}

export default function ScenarioLauncher({
  disabled,
  launching,
  jobs,
  selectedJobId,
  onLaunch,
  onInspectJob,
}: ScenarioLauncherProps) {
  const [selected, setSelected] = useState<Scenario>("A");
  const [timeLimit, setTimeLimit] = useState("");
  const [seed, setSeed] = useState("");
  const [error, setError] = useState<string | null>(null);

  const launch = async () => {
    setError(null);
    let parsed: number | undefined;
    if (timeLimit.trim() !== "") {
      parsed = Number(timeLimit);
      if (!Number.isInteger(parsed) || parsed <= 0) {
        setError("Time limit must be a positive whole number of seconds.");
        return;
      }
    }
    let parsedSeed: number | undefined;
    if (seed.trim() !== "") {
      parsedSeed = Number(seed);
      if (
        !Number.isInteger(parsedSeed) ||
        parsedSeed < 0 ||
        parsedSeed > 2_147_483_647
      ) {
        setError("Seed must be an integer from 0 to 2147483647.");
        return;
      }
    }
    try {
      await onLaunch(selected, parsed, parsedSeed);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : String(caught),
      );
    }
  };

  return (
    <Panel
      title="Scenario dispatch"
      eyebrow="Stage 3 · Optimise"
      actions={
        <span className="panel__meter">
          {disabled ? "awaiting run" : "console armed"}
        </span>
      }
    >
      <fieldset className="scenarios" disabled={disabled}>
        <legend className="sr-only">Choose scenario A, B or C</legend>
        {SCENARIOS.map((spec) => {
          const active = spec.id === selected;
          const scenarioJobs = jobs.filter((job) => job.scenario === spec.id);
          const running = scenarioJobs.find((job) => isActiveJob(job.state));
          const latest = scenarioJobs[0];
          return (
            <label
              key={spec.id}
              className={`scenario${active ? " scenario--active" : ""}`}
            >
              <input
                type="radio"
                name="scenario"
                value={spec.id}
                checked={active}
                onChange={() => setSelected(spec.id)}
                className="sr-only"
              />
              <span className="scenario__lever" aria-hidden="true">
                {spec.id}
              </span>
              <span className="scenario__body">
                <span className="scenario__title">{spec.title}</span>
                <span className="scenario__tagline">{spec.tagline}</span>
                <span className="scenario__objective">
                  <strong>Objective.</strong> {spec.objective}
                </span>
                <span className="scenario__facts">
                  <span>{spec.eclo}</span>
                  <span>{spec.capacity}</span>
                  <span>{spec.completion}</span>
                </span>
                <span className="scenario__hard">
                  <strong>Hard rules.</strong> {spec.hardRules}
                </span>
              </span>
              <span className="scenario__status">
                {running ? (
                  <>
                    <SignalLamp
                      tone={stateTone(running.state)}
                      size="sm"
                      pulse
                      label={`Scenario ${spec.id} ${running.state}`}
                    />
                    <span>{running.state}</span>
                  </>
                ) : latest ? (
                  <>
                    <SignalLamp
                      tone={stateTone(latest.state)}
                      size="sm"
                      label={`Scenario ${spec.id} last ${latest.state}`}
                    />
                    <span>last {latest.state}</span>
                  </>
                ) : (
                  <>
                    <SignalLamp tone="idle" size="sm" label="Not yet run" />
                    <span>not run</span>
                  </>
                )}
              </span>
            </label>
          );
        })}
      </fieldset>

      <div className="dispatch">
        <div className="field">
          <label htmlFor="time-limit">Time limit (seconds, optional)</label>
          <input
            id="time-limit"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder="server default"
            value={timeLimit}
            onChange={(event) => setTimeLimit(event.target.value)}
            disabled={disabled}
          />
          <p className="field__hint">
            Leave blank to use the configured solver default. Solve work is queued
            and never blocks the API.
          </p>
        </div>
        <div className="field">
          <label htmlFor="solver-seed">Solver seed (optional)</label>
          <input
            id="solver-seed"
            type="number"
            min={0}
            max={2147483647}
            step={1}
            inputMode="numeric"
            placeholder="server default"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            disabled={disabled}
          />
          <p className="field__hint">
            Pin the random seed to reproduce a schedule. Leave blank for the
            server default.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary btn--dispatch"
          onClick={launch}
          disabled={disabled || launching !== null}
        >
          {launching ? `Dispatching ${launching}…` : `Dispatch ${selected} · ${scenarioSpec(selected).tagline}`}
        </button>
      </div>

      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Dispatch failed</span>
          <p>{error}</p>
        </div>
      ) : null}

      {jobs.length > 0 ? (
        <div className="jobstrip" aria-label="Scenario jobs in this session">
          {jobs.map((job) => (
            <button
              type="button"
              key={job.id}
              className={`jobstrip__item${
                job.id === selectedJobId ? " jobstrip__item--active" : ""
              }`}
              onClick={() => onInspectJob(job)}
              aria-pressed={job.id === selectedJobId}
              title="Inspect this job"
            >
              <SignalLamp
                tone={stateTone(job.state)}
                size="sm"
                pulse={isActiveJob(job.state)}
                label={`${job.scenario} ${job.state}`}
              />
              <span className="jobstrip__id">
                {job.scenario}·{job.id.slice(0, 6)}
              </span>
              <span className="jobstrip__state">{job.state}</span>
              <span className="jobstrip__time">
                {formatDateTime(job.submitted_at)}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
