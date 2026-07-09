import { ApiError } from "../../shared/api/client";
import type { ReviewQuestion } from "../review/reviewTypes";

export interface RescanVaultResponse {
  indexed: number;
}

async function readError(response: Response, fallback: string): Promise<never> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("api_error", fallback);
  }
  if (typeof body === "object" && body !== null && "message" in body) {
    throw new ApiError("api_error", String((body as { message: unknown }).message));
  }
  if (typeof body === "object" && body !== null && "detail" in body) {
    throw new ApiError("api_error", String((body as { detail: unknown }).detail));
  }
  throw new ApiError("api_error", fallback);
}

export async function uploadSource(workspacePath: string, file: File): Promise<ReviewQuestion> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  form.set("file", file);
  const response = await fetch("/api/knowledge/sources", { method: "POST", body: form });
  if (!response.ok) await readError(response, "上传失败");
  return response.json() as Promise<ReviewQuestion>;
}

export async function rescanVault(workspacePath: string): Promise<RescanVaultResponse> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  const response = await fetch("/api/knowledge/rescan", { method: "POST", body: form });
  if (!response.ok) await readError(response, "重新扫描失败");
  return response.json() as Promise<RescanVaultResponse>;
}
