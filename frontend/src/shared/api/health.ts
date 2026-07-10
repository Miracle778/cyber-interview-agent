import { apiGet } from "./client";

export interface HealthStatus {
  status: "ok";
}

export function getHealth(): Promise<HealthStatus> {
  return apiGet<HealthStatus>("/api/health");
}
