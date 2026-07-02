export interface HealthResponse {
  status: "ok";
  version: string;
  checks: {
    database: "skipped" | "ok" | "degraded";
    providers: "not_configured" | "ok" | "degraded";
  };
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}

export interface ProfileFact {
  claim: string;
  evidence_ref: string | null;
}

export interface ProfileVersion {
  schema_name: "profile";
  schema_version: number;
  facts: ProfileFact[];
}

export interface CreateRunResponse {
  run_id: string;
}

export interface RunState {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  pending_version: { id: string; content: ProfileVersion } | null;
}

export async function createProfileRun(text: string): Promise<CreateRunResponse> {
  const response = await fetch("/api/profile/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    throw new Error(`create run failed: ${response.status}`);
  }
  return response.json() as Promise<CreateRunResponse>;
}

export async function getRun(runId: string): Promise<RunState> {
  const response = await fetch(`/api/profile/runs/${runId}`);
  if (!response.ok) {
    throw new Error(`get run failed: ${response.status}`);
  }
  return response.json() as Promise<RunState>;
}

export async function approveVersion(versionId: string): Promise<void> {
  const response = await fetch(`/api/profile/artifact-versions/${versionId}/approve`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`approve failed: ${response.status}`);
  }
}
