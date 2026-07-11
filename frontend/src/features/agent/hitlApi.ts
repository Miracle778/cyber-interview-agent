import { apiGet, apiPost } from "../../shared/api/client";
import type { PendingAction, PendingActionStatus, ResolveActionRequest } from "./hitlTypes";


export function listActions(
  workspaceId: string,
  options: { status?: PendingActionStatus; sessionId?: string } = {},
): Promise<PendingAction[]> {
  const query = new URLSearchParams({ workspaceId });
  if (options.status) query.set("status", options.status);
  if (options.sessionId) query.set("sessionId", options.sessionId);
  return apiGet<PendingAction[]>(`/api/agent/actions?${query.toString()}`);
}

export function getAction(actionId: string): Promise<PendingAction> {
  return apiGet<PendingAction>(`/api/agent/actions/${actionId}`);
}

export function approveAction(
  actionId: string,
  request: ResolveActionRequest,
): Promise<PendingAction> {
  return apiPost<ResolveActionRequest, PendingAction>(
    `/api/agent/actions/${actionId}/approve`,
    request,
  );
}

export function rejectAction(
  actionId: string,
  request: ResolveActionRequest,
): Promise<PendingAction> {
  return apiPost<ResolveActionRequest, PendingAction>(
    `/api/agent/actions/${actionId}/reject`,
    request,
  );
}
