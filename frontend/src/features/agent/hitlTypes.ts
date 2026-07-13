export type PendingActionStatus =
  | "pending"
  | "approved"
  | "edited_and_approved"
  | "rejected"
  | "cancelled";

export interface PendingAction {
  id: string;
  workspaceId: string;
  sessionId: string;
  executionId: string;
  actionType: string;
  preview: Record<string, unknown>;
  editableFields: string[];
  status: PendingActionStatus;
  version: number;
  createdAt: string;
  resolvedAt: string | null;
}

export interface ResolveActionRequest {
  version: number;
  idempotencyKey: string;
  editedPayload?: Record<string, unknown>;
  reason?: string;
}
