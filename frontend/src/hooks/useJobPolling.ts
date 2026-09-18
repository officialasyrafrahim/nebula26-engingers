import { useEffect, useState } from "react";

import { getJob } from "../api/client";
import { isActiveJob, type ScenarioJob } from "../api/types";

const POLL_INTERVAL_MS = 1500;
const ERROR_RETRY_MS = 4000;

export interface JobPollResult {
  job: ScenarioJob | null;
  error: string | null;
}

// Polls a scenario job until it reaches a terminal lifecycle state. The hook
// only reads server state; it never derives scheduling facts.
export function useJobPolling(
  runId: string | null,
  jobId: string | null,
): JobPollResult {
  const [job, setJob] = useState<ScenarioJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId || !jobId) {
      setJob(null);
      setError(null);
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const next = await getJob(runId, jobId);
        if (cancelled) return;
        setJob(next);
        setError(null);
        if (isActiveJob(next.state)) {
          timer = window.setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : String(caught));
        timer = window.setTimeout(tick, ERROR_RETRY_MS);
      }
    };

    void tick();

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId, jobId]);

  return { job, error };
}
