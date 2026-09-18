import { useState } from "react";

import { ApiError, downloadBlob, exportZip } from "../api/client";
import type { ValidatorReport } from "../api/types";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface DownloadPanelProps {
  runId: string;
  jobId: string;
  scenario: string;
  report: ValidatorReport;
}

export default function DownloadPanel({
  runId,
  jobId,
  scenario,
  report,
}: DownloadPanelProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<string | null>(null);
  const ready = report.ready_for_submission;
  const provisional = report.authority === "fallback";

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await exportZip(runId, jobId, scenario);
      downloadBlob(blob, filename);
      setDownloaded(filename);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : String(caught),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Submission export"
      eyebrow={`Stage 6 · Export · scenario ${scenario}`}
      tone={ready ? (provisional ? "warn" : "ok") : "danger"}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={ready ? (provisional ? "warn" : "ok") : "danger"}
            size="sm"
            label={
              ready
                ? provisional
                  ? "Provisional export enabled"
                  : "Export enabled"
                : "Export blocked"
            }
          />
          <span>
            {ready ? (provisional ? "provisional gate" : "gate open") : "gate blocked"}
          </span>
        </span>
      }
    >
      <p className="export__copy">
        {ready
          ? provisional
            ? "The fallback validator gate has passed, so export is enabled. Download the per-scenario zip containing SCHEDULE_ACCESS.csv, SCHEDULE_OCCUPANCY.csv and RESULTS.csv."
            : "The official validator gate has passed. Download the per-scenario zip containing SCHEDULE_ACCESS.csv, SCHEDULE_OCCUPANCY.csv and RESULTS.csv."
          : "Export is withheld until the validator gate reports ready for submission. Resolve the hard violations above and re-dispatch the scenario."}
      </p>

      {provisional ? (
        <p className="export__provisional">
          Provisional: the validation shown here is the current interpretation of the
          published rules by the bundled fallback authority. No official validator was
          configured, so this is not authoritative acceptance.
        </p>
      ) : null}

      {error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Download failed</span>
          <p>{error}</p>
        </div>
      ) : null}

      {downloaded ? (
        <div className="notice notice--ok" role="status">
          <span className="notice__title">Downloaded {downloaded}</span>
        </div>
      ) : null}

      <div className="panel__footer">
        <span className="panel__hint">
          Zip includes the three submission CSVs for scenario {scenario}.
        </span>
        <button
          type="button"
          className="btn btn--primary"
          onClick={download}
          disabled={!ready || busy}
        >
          {busy
            ? "Preparing zip…"
            : provisional
              ? "Download provisional zip"
              : "Download submission zip"}
        </button>
      </div>
    </Panel>
  );
}
