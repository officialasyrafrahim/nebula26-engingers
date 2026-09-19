import { useState } from "react";

import { ApiError, downloadBlob, exportZip } from "../api/client";
import type { ValidatorReport } from "../api/types";
import { deriveAuthorityClaim } from "../lib/assurance";
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
  const claim = deriveAuthorityClaim(report.authority, report.validator_source);
  const provisional = claim.provisional;
  const disputed = claim.mismatch;
  const ready = report.ready_for_submission && !disputed;
  const tone = disputed ? "danger" : ready ? (provisional ? "warn" : "ok") : "danger";
  const gateLabel = disputed
    ? "Export withheld: authority disagreement"
    : ready
      ? provisional
        ? "Provisional export enabled"
        : "Export enabled"
      : "Export blocked";

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
      tone={tone}
      actions={
        <span className="gate-inline">
          <SignalLamp
            tone={tone}
            size="sm"
            label={gateLabel}
          />
          <span>
            {disputed
              ? "authority disputed"
              : ready
                ? provisional
                  ? "provisional gate"
                  : "gate open"
                : "gate blocked"}
          </span>
        </span>
      }
    >
      <p className="export__copy">
        {disputed
          ? "Export is withheld: the report's validator authority and the recorded source disagree, so no official gate status can be claimed. Do not treat this as an accepted submission."
          : ready
            ? provisional
              ? "The fallback validator gate has passed, so export is enabled. Download the per-scenario zip containing SCHEDULE_ACCESS.csv, SCHEDULE_OCCUPANCY.csv and RESULTS.csv."
              : "The official validator gate has passed. Download the per-scenario zip containing SCHEDULE_ACCESS.csv, SCHEDULE_OCCUPANCY.csv and RESULTS.csv."
            : "Export is withheld until the validator gate reports ready for submission. Resolve the hard violations above and re-dispatch the scenario."}
      </p>

      {disputed ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Validator authority disagreement</span>
          <p>
            The report claims authority &quot;{report.authority}&quot; but was
            recorded by &quot;{report.validator_source}&quot;. Export is withheld
            rather than presenting a disputed result as official.
          </p>
        </div>
      ) : null}

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
          {disputed
            ? "Export withheld"
            : busy
              ? "Preparing zip…"
              : provisional
                ? "Download provisional zip"
                : "Download submission zip"}
        </button>
      </div>
    </Panel>
  );
}
