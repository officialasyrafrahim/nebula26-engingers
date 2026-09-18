import { useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { ApiError, type IssueDetail } from "../api/client";
import {
  INSTANCE_FILES,
  INSTANCE_FILE_NAMES,
  basename,
} from "../lib/instanceFiles";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface UploadPanelProps {
  onUpload: (files: File[]) => Promise<void>;
}

interface ParseFailure {
  message: string;
  issues: IssueDetail[];
}

interface LocalIssue {
  file: string;
  message: string;
}

export default function UploadPanel({ onUpload }: UploadPanelProps) {
  const [selected, setSelected] = useState<Record<string, File>>({});
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ParseFailure | null>(null);
  const [unexpected, setUnexpected] = useState<LocalIssue[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const present = useMemo(
    () => INSTANCE_FILE_NAMES.filter((name) => name in selected),
    [selected],
  );
  const missing = useMemo(
    () => INSTANCE_FILE_NAMES.filter((name) => !(name in selected)),
    [selected],
  );

  const addFiles = (incoming: FileList | File[]) => {
    const next: Record<string, File> = { ...selected };
    const rejected: LocalIssue[] = [];
    for (const file of Array.from(incoming)) {
      const name = basename(file.name);
      if (!INSTANCE_FILE_NAMES.includes(name)) {
        rejected.push({ file: name, message: "not one of the eight instance files" });
        continue;
      }
      next[name] = file;
    }
    setSelected(next);
    setUnexpected(rejected);
    setFailure(null);
  };

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) addFiles(event.target.files);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
  };

  const removeFile = (name: string) => {
    setSelected((current) => {
      const next = { ...current };
      delete next[name];
      return next;
    });
    setFailure(null);
  };

  const clearAll = () => {
    setSelected({});
    setUnexpected([]);
    setFailure(null);
  };

  const submit = async () => {
    if (missing.length > 0) return;
    setBusy(true);
    setFailure(null);
    try {
      await onUpload(INSTANCE_FILE_NAMES.map((name) => selected[name]));
      setSelected({});
      setUnexpected([]);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFailure({ message: caught.message, issues: caught.issues });
      } else {
        setFailure({
          message: caught instanceof Error ? caught.message : String(caught),
          issues: [],
        });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Instance intake"
      eyebrow="Stage 1 · Ingest"
      tone={failure ? "danger" : "default"}
      actions={
        <span className="panel__meter">
          {present.length}/{INSTANCE_FILE_NAMES.length} files staged
        </span>
      }
    >
      <div
        className={`dropzone${dragging ? " dropzone--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          id="instance-files"
          className="sr-only"
          type="file"
          multiple
          accept=".csv,text/csv"
          onChange={handleInput}
          aria-label="Select the eight instance CSV files"
        />
        <div className="dropzone__rail" aria-hidden="true" />
        <p className="dropzone__lead">
          Drop all eight named CSVs here, or choose them individually.
        </p>
        <div className="dropzone__controls">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            Choose files
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={clearAll}
            disabled={busy || present.length === 0}
          >
            Clear
          </button>
        </div>
      </div>

      <ul className="checklist" aria-label="Required instance files">
        {INSTANCE_FILES.map((spec) => {
          const file = selected[spec.name];
          return (
            <li
              key={spec.name}
              className={`checklist__item${file ? " checklist__item--ok" : ""}`}
            >
              <SignalLamp
                tone={file ? "ok" : "idle"}
                size="sm"
                label={file ? `${spec.name} staged` : `${spec.name} missing`}
              />
              <div className="checklist__text">
                <span className="checklist__name">{spec.name}</span>
                <span className="checklist__label">{spec.label}</span>
                <span className="checklist__columns">{spec.columns}</span>
              </div>
              {file ? (
                <>
                  <span className="checklist__file" title={file.name}>
                    {file.name}
                  </span>
                  <button
                    type="button"
                    className="btn btn--tiny"
                    onClick={() => removeFile(spec.name)}
                    aria-label={`Remove ${spec.name}`}
                  >
                    ✕
                  </button>
                </>
              ) : (
                <span className="checklist__file checklist__file--missing">
                  required
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {unexpected.length > 0 ? (
        <div className="notice notice--warn" role="status">
          <span className="notice__title">Ignored files</span>
          <ul className="notice__list">
            {unexpected.map((issue, index) => (
              <li key={`${issue.file}-${index}`}>
                <code>{issue.file}</code> — {issue.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {failure ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Upload rejected: {failure.message}</span>
          {failure.issues.length > 0 ? (
            <ul className="notice__list" aria-label="Parse errors">
              {failure.issues.map((issue, index) => (
                <li key={index}>
                  <code>{issue.file ?? "instance"}</code>
                  {issue.row != null ? <span> row {issue.row}</span> : null}
                  {issue.column ? <span> col {issue.column}</span> : null}
                  {issue.value ? <span> value {issue.value}</span> : null}
                  <span> — {issue.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="panel__footer">
        <p className="panel__hint" role="status" aria-live="polite">
          {missing.length === 0
            ? "All eight files staged. Ready to compile."
            : `Waiting on ${missing.length} file${missing.length === 1 ? "" : "s"}: ${missing.join(", ")}`}
        </p>
        <button
          type="button"
          className="btn btn--primary"
          onClick={submit}
          disabled={busy || missing.length > 0}
        >
          {busy ? "Compiling…" : "Compile planning run"}
        </button>
      </div>
    </Panel>
  );
}
