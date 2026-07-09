import { apiPost } from "../../shared/api/client";
import type { ReviewQuestion } from "./reviewTypes";

export interface ReviewRunRequest {
  questions: ReviewQuestion[];
  settings: {
    selectedTopics: string[];
    questionCount: number;
    mode: "weak-point" | "random-mixed" | "topic-focused" | "recent-mistake";
  };
  userAnswer: string;
}

export interface ReviewRunResponse {
  current_question: ReviewQuestion;
  evaluation: {
    score: "poor" | "partial" | "good";
    missing_key_points: string[];
    evidence: string;
  };
  report_markdown: string;
}

export interface ConfirmReportRequest {
  workspacePath: string;
  reportMarkdown: string;
}

export interface ConfirmReportResponse {
  reportPath: string;
  masteryPath: string;
}

export function runReview(payload: ReviewRunRequest): Promise<ReviewRunResponse> {
  return apiPost<ReviewRunRequest, ReviewRunResponse>("/api/review/run", payload);
}

export function confirmReport(payload: ConfirmReportRequest): Promise<ConfirmReportResponse> {
  return apiPost<ConfirmReportRequest, ConfirmReportResponse>("/api/review/reports/confirm", payload);
}
