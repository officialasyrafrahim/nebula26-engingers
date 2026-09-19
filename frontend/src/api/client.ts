// Typed fetch client for the Rail Access Optimisation API.
//
// The base URL is relative by default so Vite serves it through the dev proxy.
// Set VITE_API_ORIGIN (e.g. http://localhost:8000) to target the backend
// directly, which is also the production deployment shape. Error bodies are
// parsed for structured 422 issue lists; binary export returns a Blob plus the
// server-provided filename.

import type {
  DatamallNetworkContext,
  DatamallStatusResponse,
  HealthStatus,
  NetworkResponse,
  PlanningRun,
  ReplanRead,
  ReplanRequest,
  SandboxRead,
  SandboxRequest,
  ScenarioJob,
  ScenarioJobCreate,
  ScheduleQueryRequest,
  ScheduleQueryResponse,
  ScheduleResponse,
  ValidatorReportRead,
} from "./types";

const rawOrigin = import.meta.env.VITE_API_ORIGIN as string | undefined;
const origin = rawOrigin ? rawOrigin.replace(/\/+$/, "") : "";
const API_BASE = `${origin}/api/v1`;

export const HEALTH_URL = `${origin}/healthz`;

export interface IssueDetail {
  file?: string | null;
  row?: number | null;
  column?: string | null;
  value?: string | null;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly issues: IssueDetail[];

  constructor(status: number, message: string, issues: IssueDetail[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.issues = issues;
  }
}

function readDetail(body: unknown, fallback: string): {
  message: string;
  issues: IssueDetail[];
} {
  if (!body || typeof body !== "object") {
    return { message: fallback, issues: [] };
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return { message: detail, issues: [] };
  }
  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; issues?: unknown };
    const message =
      typeof record.message === "string" ? record.message : fallback;
    const issues: IssueDetail[] = [];
    if (Array.isArray(record.issues)) {
      for (const entry of record.issues) {
        if (!entry || typeof entry !== "object") continue;
        const issue = entry as Record<string, unknown>;
        if (typeof issue.message !== "string") continue;
        issues.push({
          file: typeof issue.file === "string" ? issue.file : null,
          row: typeof issue.row === "number" ? issue.row : null,
          column: typeof issue.column === "string" ? issue.column : null,
          value: issue.value == null ? null : String(issue.value),
          message: issue.message,
        });
      }
    }
    return { message, issues };
  }
  return { message: fallback, issues: [] };
}

async function toApiError(response: Response): Promise<ApiError> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const { message, issues } = readDetail(body, fallback);
  return new ApiError(response.status, message, issues);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const quoted = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  if (!quoted) return null;
  try {
    return decodeURIComponent(quoted[1]);
  } catch {
    return quoted[1];
  }
}

export function healthCheck(): Promise<HealthStatus> {
  return fetch(HEALTH_URL).then(async (response) => {
    if (!response.ok) throw await toApiError(response);
    return (await response.json()) as HealthStatus;
  });
}

export function listRuns(): Promise<PlanningRun[]> {
  return request<PlanningRun[]>("/runs");
}

export function getRun(runId: string): Promise<PlanningRun> {
  return request<PlanningRun>(`/runs/${runId}`);
}

export function createRun(files: File[]): Promise<PlanningRun> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
  }
  return request<PlanningRun>("/runs", { method: "POST", body: form });
}

export function getNetwork(runId: string): Promise<NetworkResponse> {
  return request<NetworkResponse>(`/runs/${runId}/network`);
}

export function listJobs(runId: string): Promise<ScenarioJob[]> {
  return request<ScenarioJob[]>(`/runs/${runId}/jobs`);
}

export function createJob(
  runId: string,
  payload: ScenarioJobCreate,
): Promise<ScenarioJob> {
  return request<ScenarioJob>(`/runs/${runId}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getJob(runId: string, jobId: string): Promise<ScenarioJob> {
  return request<ScenarioJob>(`/runs/${runId}/jobs/${jobId}`);
}

export function cancelJob(runId: string, jobId: string): Promise<ScenarioJob> {
  return request<ScenarioJob>(`/runs/${runId}/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export function getSchedule(
  runId: string,
  jobId: string,
): Promise<ScheduleResponse> {
  return request<ScheduleResponse>(`/runs/${runId}/jobs/${jobId}/schedule`);
}

export function getReport(
  runId: string,
  jobId: string,
): Promise<ValidatorReportRead> {
  return request<ValidatorReportRead>(`/runs/${runId}/jobs/${jobId}/report`);
}

export function createReplan(
  runId: string,
  jobId: string,
  payload: ReplanRequest,
): Promise<ReplanRead> {
  return request<ReplanRead>(`/runs/${runId}/jobs/${jobId}/replan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getReplan(
  runId: string,
  replanId: string,
): Promise<ReplanRead> {
  return request<ReplanRead>(`/runs/${runId}/replans/${replanId}`);
}

// Advisory only. A sandbox what-if re-solves on the server and returns baseline
// against variant metrics. It never rewrites the source job's published CSVs.
export function createSandbox(
  runId: string,
  jobId: string,
  payload: SandboxRequest,
): Promise<SandboxRead> {
  return request<SandboxRead>(`/runs/${runId}/jobs/${jobId}/sandbox`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// A deterministic, closed-grammar query. Unsupported shapes are rejected by the
// server with HTTP 422; an answerable query carries its own citations.
export function querySchedule(
  runId: string,
  jobId: string,
  payload: ScheduleQueryRequest,
): Promise<ScheduleQueryResponse> {
  return request<ScheduleQueryResponse>(`/runs/${runId}/jobs/${jobId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface ExportDownload {
  blob: Blob;
  filename: string;
}

export async function exportZip(
  runId: string,
  jobId: string,
  scenario: string,
): Promise<ExportDownload> {
  const response = await fetch(`${API_BASE}/runs/${runId}/jobs/${jobId}/export`);
  if (!response.ok) {
    throw await toApiError(response);
  }
  const blob = await response.blob();
  const filename =
    filenameFromDisposition(response.headers.get("Content-Disposition")) ??
    `scenario-${scenario}.zip`;
  return { blob, filename };
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// ------------------------------------------------------- LTA DataMall context
// Advisory only. These calls never change solver state and are safe to fail.

export function getDatamallContext(
  networkKey: string,
): Promise<DatamallNetworkContext> {
  return request<DatamallNetworkContext>(
    `/context/datamall/context?network=${encodeURIComponent(networkKey)}`,
  );
}

export function getDatamallStatus(): Promise<DatamallStatusResponse> {
  return request<DatamallStatusResponse>("/context/datamall/status");
}
