export type KnowledgeDraftStatus = "draft" | "review_pending" | "rejected" | "published" | "superseded";

export interface PublicationSummary {
  state: "prepared" | "file_written" | "indexed" | "completed" | "index_stale" | "failed";
  targetPath: string;
  errorCode: string | null;
}

export interface KnowledgeDraft {
  id: string;
  workspaceId: string;
  sessionId: string | null;
  executionId: string | null;
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
  publication: PublicationSummary | null;
}
