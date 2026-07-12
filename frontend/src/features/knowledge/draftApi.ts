import { apiGet, apiPatch, apiPost } from "../../shared/api/client";
import type { KnowledgeDraft } from "./draftTypes";

export interface UpdateKnowledgeDraftRequest {
  version: number;
  title?: string;
  markdown: string;
}

export interface PublishDraftRunResource {
  sessionId: string;
  runId: string;
  status: string;
}

export function listDrafts(workspaceId: string): Promise<KnowledgeDraft[]> {
  const query = new URLSearchParams({ workspaceId });
  return apiGet<KnowledgeDraft[]>(`/api/knowledge/drafts?${query.toString()}`);
}

export function getDraft(draftId: string): Promise<KnowledgeDraft> {
  return apiGet<KnowledgeDraft>(`/api/knowledge/drafts/${draftId}`);
}

export function updateDraft(
  draftId: string,
  request: UpdateKnowledgeDraftRequest,
): Promise<KnowledgeDraft> {
  return apiPatch<UpdateKnowledgeDraftRequest, KnowledgeDraft>(
    `/api/knowledge/drafts/${draftId}`,
    request,
  );
}

export function requestPublication(draftId: string): Promise<PublishDraftRunResource> {
  return apiPost<Record<string, never>, PublishDraftRunResource>(
    `/api/knowledge/drafts/${draftId}/publish-request`,
    {},
  );
}
