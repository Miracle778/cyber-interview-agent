export type DocumentStatus = "draft" | "review_pending" | "reviewed" | "ingested" | "stale" | "archived";
export type DocumentType = "source" | "question" | "concept" | "session_report" | "mastery_report";

export interface VaultDocument {
  id: string;
  path: string;
  title: string;
  type: DocumentType;
  status: DocumentStatus;
  updatedAt: string;
}
