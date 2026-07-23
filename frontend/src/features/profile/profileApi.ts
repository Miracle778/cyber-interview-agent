import { apiGet, apiPost, apiUpload } from "../../shared/api/client";
import type { AgentSession } from "../agent/agentTypes";
import type { AcceptedMaterialRetry, AcceptedMaterialUpload, BatchClaimDecisionResult, ClaimDecision, ClaimDecisionResult, MaterialDeletionPreview, PermanentMaterialDeletionResult, ProfileActionPlan, ProfileAssessment, ProfileClaimWorkspace, ProfileMaterial, ProfileMaterialVersion, ProfileMaterialVersionDetail } from "./profileTypes";

function commandKey(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

function commandOptions(idempotencyKey = commandKey("profile"), signal?: AbortSignal) {
  return { headers: { "Idempotency-Key": idempotencyKey }, signal };
}

export function listProfileMaterials(workspaceId: string, includeArchived = true, signal?: AbortSignal) {
  return apiGet<ProfileMaterial[]>(`/api/workspaces/${workspaceId}/profile/materials?includeArchived=${includeArchived}`, { signal });
}

export function uploadProfileMaterial(workspaceId: string, file: File, metadata: { title: string; primaryRole: string }, idempotencyKey = commandKey("profile-upload"), signal?: AbortSignal) {
  const body = new FormData();
  body.set("title", metadata.title);
  body.set("primaryRole", metadata.primaryRole);
  body.set("file", file);
  return apiUpload<AcceptedMaterialUpload>(`/api/workspaces/${workspaceId}/profile/materials`, body, commandOptions(idempotencyKey, signal));
}

export function addMaterialVersion(workspaceId: string, materialId: string, file: File, idempotencyKey = commandKey("profile-version"), signal?: AbortSignal) {
  const body = new FormData();
  body.set("workspaceId", workspaceId);
  body.set("file", file);
  return apiUpload<AcceptedMaterialUpload>(`/api/profile/materials/${materialId}/versions`, body, commandOptions(idempotencyKey, signal));
}

export function listMaterialVersions(workspaceId: string, materialId: string, signal?: AbortSignal) {
  return apiGet<ProfileMaterialVersion[]>(`/api/profile/materials/${materialId}/versions?workspaceId=${encodeURIComponent(workspaceId)}`, { signal });
}

export function getMaterialVersion(workspaceId: string, versionId: string, signal?: AbortSignal) {
  return apiGet<ProfileMaterialVersionDetail>(`/api/profile/material-versions/${versionId}?workspaceId=${encodeURIComponent(workspaceId)}&evidenceLimit=50`, { signal });
}

export function retryMaterialVersion(workspaceId: string, versionId: string, idempotencyKey = commandKey("profile-retry")) {
  return apiPost<{ workspaceId: string }, AcceptedMaterialRetry>(`/api/profile/material-versions/${versionId}/retry`, { workspaceId }, commandOptions(idempotencyKey));
}

export function archiveMaterial(workspaceId: string, material: ProfileMaterial, idempotencyKey = commandKey("profile-archive")) {
  return apiPost(`/api/profile/materials/${material.id}/archive`, { workspaceId, expectedVersion: material.version }, commandOptions(idempotencyKey)) as Promise<ProfileMaterial>;
}

export function restoreMaterial(workspaceId: string, material: ProfileMaterial, idempotencyKey = commandKey("profile-restore")) {
  return apiPost(`/api/profile/materials/${material.id}/restore`, { workspaceId, expectedVersion: material.version }, commandOptions(idempotencyKey)) as Promise<ProfileMaterial>;
}

export function setPrimaryVersion(workspaceId: string, material: ProfileMaterial, versionId: string, idempotencyKey = commandKey("profile-primary")) {
  return apiPost(`/api/profile/materials/${material.id}/primary`, { workspaceId, expectedVersion: material.version, versionId }, commandOptions(idempotencyKey)) as Promise<ProfileMaterial>;
}

export function listProfileClaims(workspaceId: string, signal?: AbortSignal) {
  return apiGet<ProfileClaimWorkspace>(`/api/workspaces/${workspaceId}/profile/claims`, { signal });
}

export function decideClaimProposal(workspaceId: string, proposalId: string, decision: ClaimDecision, expectedVersion: number, editedValue?: Record<string, unknown>, idempotencyKey = commandKey("profile-claim-decision")) {
  return apiPost(`/api/profile/claim-proposals/${proposalId}/${decision === "accepted" ? "accept" : "reject"}`, { workspaceId, expectedVersion, ...(editedValue ? { editedValue } : {}) }, commandOptions(idempotencyKey)) as Promise<ClaimDecisionResult>;
}

export function batchDecideClaimProposals(workspaceId: string, decisions: { proposalId: string; decision: ClaimDecision; expectedVersion: number; editedValue?: Record<string, unknown> }[], idempotencyKey = commandKey("profile-claim-batch")) {
  return apiPost("/api/profile/claim-proposals/batch-decide", { workspaceId, decisions }, commandOptions(idempotencyKey)) as Promise<BatchClaimDecisionResult>;
}

export function previewMaterialDeletion(workspaceId: string, material: ProfileMaterial, idempotencyKey = commandKey("profile-delete-preview")) {
  return apiPost(`/api/profile/materials/${material.id}/deletion-preview`, { workspaceId, expectedVersion: material.version }, commandOptions(idempotencyKey)) as Promise<MaterialDeletionPreview>;
}

export function permanentlyDeleteMaterial(workspaceId: string, material: ProfileMaterial, preview: MaterialDeletionPreview, claimChoices: { claimId: string; action: "delete" | "retain_unsupported" }[], activePublicationAction: "revoke" | "not_applicable", idempotencyKey = commandKey("profile-delete")) {
  return apiPost(`/api/profile/materials/${material.id}/permanent-delete`, { workspaceId, expectedVersion: material.version, deletionPlanId: preview.deletionPlanId, claimChoices, activePublicationAction }, commandOptions(idempotencyKey)) as Promise<PermanentMaterialDeletionResult>;
}

export function createProfileSession(workspaceId: string, title?: string) {
  return apiPost(`/api/workspaces/${workspaceId}/profile/sessions`, { ...(title ? { title } : {}) }) as Promise<AgentSession>;
}

export function listProfileSessions(workspaceId: string, signal?: AbortSignal) {
  return apiGet<AgentSession[]>(`/api/workspaces/${workspaceId}/profile/sessions`, { signal });
}

export function getProfileAssessment(workspaceId: string, assessmentId: string, signal?: AbortSignal) {
  return apiGet<ProfileAssessment>(`/api/profile/assessments/${assessmentId}?workspaceId=${encodeURIComponent(workspaceId)}`, { signal });
}

export function getProfileActionPlan(workspaceId: string, planId: string, signal?: AbortSignal) {
  return apiGet<ProfileActionPlan>(`/api/profile/action-plans/${planId}?workspaceId=${encodeURIComponent(workspaceId)}`, { signal });
}

export function confirmProfileActionPlan(workspaceId: string, plan: ProfileActionPlan) {
  return apiPost(`/api/profile/action-plans/${plan.id}/confirm`, { workspaceId, expectedVersion: plan.version }) as Promise<ProfileActionPlan>;
}

export function cancelProfileActionPlan(workspaceId: string, plan: ProfileActionPlan) {
  return apiPost(`/api/profile/action-plans/${plan.id}/cancel`, { workspaceId, expectedVersion: plan.version }) as Promise<ProfileActionPlan>;
}

export function retryProfileActionPlan(workspaceId: string, planId: string) {
  return apiPost(`/api/profile/action-plans/${planId}/retry`, { workspaceId }) as Promise<ProfileActionPlan>;
}
