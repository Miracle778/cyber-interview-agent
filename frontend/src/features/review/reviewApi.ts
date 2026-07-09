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

export function runReview(payload: ReviewRunRequest): Promise<Record<string, unknown>> {
  return apiPost<ReviewRunRequest, Record<string, unknown>>("/api/review/run", payload);
}
