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

