import { ApiError, apiGet } from "../../shared/api/client";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { KnowledgeDraft } from "./draftTypes";
import type { KnowledgeSource } from "./knowledgeTypes";

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

export interface UploadSourceResponse {
  source: KnowledgeSource;
  draft: KnowledgeDraft;
  question: ReviewQuestion;
}

export function listSources(workspaceId: string): Promise<KnowledgeSource[]> {
  const query = new URLSearchParams({ workspaceId });
  return apiGet<KnowledgeSource[]>(`/api/knowledge/sources?${query.toString()}`);
}

export async function uploadSource(workspaceId: string, file: File): Promise<UploadSourceResponse> {
  const form = new FormData();
  form.set("workspaceId", workspaceId);
  form.set("file", file);
  const response = await fetch("/api/knowledge/sources", { method: "POST", body: form });
  if (!response.ok) await readError(response, "上传失败");
  return response.json() as Promise<UploadSourceResponse>;
}

export async function rescanVault(workspaceId: string): Promise<RescanVaultResponse> {
  const form = new FormData();
  form.set("workspaceId", workspaceId);
  const response = await fetch("/api/knowledge/rescan", { method: "POST", body: form });
  if (!response.ok) await readError(response, "重新扫描失败");
  return response.json() as Promise<RescanVaultResponse>;
}
