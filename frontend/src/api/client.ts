const API_BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export type HealthStatus = Record<string, unknown>;

export async function healthCheck(): Promise<HealthStatus> {
  const response = await fetch("/healthz");
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as HealthStatus;
}

export type Asset = Record<string, unknown>;
export type WorkPackage = Record<string, unknown>;
export type PlanJob = Record<string, unknown>;
export type Proposal = Record<string, unknown>;
export type AssistantQuestion = {
  question: string;
  assessment_id?: string;
  work_package_id?: string;
  proposal_id?: string;
};
export type AssistantAnswer = {
  question: string;
  answer: string;
  llm_used: boolean;
  llm_status: "disabled" | "unconfigured" | "ok" | "unavailable";
  structured_context: Record<string, unknown>;
};

// TODO: wire UI views for the placeholder lists below.
export function listAssets(): Promise<Asset[]> {
  return request<Asset[]>(`${API_BASE}/assets`);
}

export function listWorkPackages(): Promise<WorkPackage[]> {
  return request<WorkPackage[]>(`${API_BASE}/work-packages`);
}

export function listPlanJobs(): Promise<PlanJob[]> {
  return request<PlanJob[]>(`${API_BASE}/planning/jobs`);
}

export function submitPlanJob(body: unknown): Promise<PlanJob> {
  return request<PlanJob>(`${API_BASE}/planning/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listProposals(): Promise<Proposal[]> {
  return request<Proposal[]>(`${API_BASE}/planning/proposals`);
}

export function askAssistant(body: AssistantQuestion): Promise<AssistantAnswer> {
  return request<AssistantAnswer>(`${API_BASE}/assistant/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
