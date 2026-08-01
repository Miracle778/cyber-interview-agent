import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuestionTimeline } from "./QuestionTimeline";
import type { AnalysisWorkItem, InterviewQuestion, QuestionAnalysis } from "./retrospectiveTypes";

const questions: InterviewQuestion[] = [
  { id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "project", origin: "original", questionText: "你如何治理缓存？", questionSegmentIds: ["s-1"], answerSegmentIds: ["s-2"], inferenceBasis: "", confidence: .99, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" },
  { id: "q-2", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 2, questionKind: "follow_up", origin: "inferred", questionText: "缓存击穿如何处理？", questionSegmentIds: [], answerSegmentIds: ["s-3"], inferenceBasis: "由回答中的热 Key 推断", confidence: .72, decisionStatus: "pending", version: 1, createdAt: "now", updatedAt: "now" },
];
const analyses: QuestionAnalysis[] = [{ id: "a-1", analysisRunId: "run-1", questionUnitId: "q-1", verdict: "high_risk", strengths: [], improvements: [], omissions: [], gaps: [], evidenceLevel: "direct", confidence: .9, improvementOutline: [], suggestedAnswer: "", sourceExcerpt: "", sourceAvailable: true, resultStatus: "completed", version: 1 }];
const items: AnalysisWorkItem[] = [
  { id: "i-1", questionUnitId: "q-1", workKey: "question_analysis:q-1", status: "retryable", attemptCount: 1, lastErrorCode: "provider_timeout", updatedAt: "now" },
  { id: "i-2", questionUnitId: "q-2", workKey: "question_analysis:q-2", status: "pending", attemptCount: 0, lastErrorCode: null, updatedAt: "now" },
];

describe("QuestionTimeline", () => {
  it("emphasizes failures and keeps inferred questions available for confirmation", () => {
    const onSelect = vi.fn();
    render(<QuestionTimeline questions={questions} analyses={analyses} items={items} selectedId="q-1" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /你如何治理缓存/ })).toHaveAttribute("data-state", "failed");
    expect(screen.getByText("分析失败")).toBeVisible();
    expect(screen.getByText("推断题")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /缓存击穿如何处理/ }));
    expect(onSelect).toHaveBeenCalledWith("q-2");
  });
});
