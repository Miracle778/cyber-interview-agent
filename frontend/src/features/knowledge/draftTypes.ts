export type KnowledgeDraftStatus = "draft" | "review_pending" | "rejected" | "published";

export interface KnowledgeDraft {
  id: string;
  workspaceId: string;
  sessionId: string | null;
  runId: string | null;
  agentType: string | null;
  domain: string;
  documentType: "source" | "question" | "concept" | "session_report" | "mastery_report";
  documentId: string;
  title: string;
  markdown: string;
  contentPath: string;
  sourceRefs: string[];
  relationRefs: string[];
  status: KnowledgeDraftStatus;
  version: number;
  contentHash: string;
  createdAt: string;
  updatedAt: string;
}
