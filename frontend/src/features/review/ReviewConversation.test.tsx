import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewConversation } from "./ReviewConversation";
import type { ReviewRound } from "./reviewTypes";

const round = {
  id: "r1", workspaceId: "w1", sessionId: "s1", executionId: "e1",
  settings: { topics: [], difficulties: ["medium"], mode: "random-mixed", question_count: 2, allow_follow_up: false, seed: 1, answer_model_id: "m1", reasoning_effort: "none" },
  status: "running", executionStatus: "running", currentIndex: 0, questionCount: 2,
  currentQuestion: { id: "q1", title: "MVCC", questionText: "Explain MVCC", topics: ["database"], difficulty: "medium" }, currentInput: null,
  attempts: [{ id: "a1", roundId: "r1", ordinal: 1, questionSnapshot: { questionId: "q1", documentId: "d1", contentHash: "h", title: "MVCC", questionText: "Explain MVCC", referenceAnswer: "versions", topics: ["database"], difficulty: "medium", keyPoints: ["versions"], followUps: [] }, answer: "multiple versions", followUpAnswer: null, evaluation: null, masterySuggestion: null, skipped: false, status: "evaluating", evaluationErrorCode: null, evaluationStartedAt: "now", evaluationCompletedAt: null, createdAt: "now", updatedAt: "now" }],
  messages: [{ id: "m1", executionId: "e1", role: "assistant", content: "Explain MVCC", messageKind: "review_prompt", payload: {}, createdAt: "now" }, { id: "m2", executionId: "e1", role: "user", content: "multiple versions", messageKind: "review_answer", payload: {}, createdAt: "now" }],
  reports: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "now", updatedAt: "now", completedAt: null,
} as ReviewRound;

describe("ReviewConversation", () => {
  it("renders ordered messages and a named evaluation stage without chain of thought", () => {
    render(<ReviewConversation round={round} optimisticMessage={null} busy={false} onSubmit={vi.fn()} onSkip={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
    const log = screen.getByRole("log", { name: "复习对话" });
    expect(log).toHaveTextContent("Explain MVCC");
    expect(log).toHaveTextContent("multiple versions");
    expect(log).toHaveTextContent("正在评价回答");
    expect(log).not.toHaveTextContent("思维链");
  });

  it("offers retry for a failed evaluation without asking for the answer again", () => {
    const retry = vi.fn();
    const failed = { ...round, attempts: [{ ...round.attempts[0], status: "evaluation_failed", evaluationErrorCode: "provider_error" }] } as ReviewRound;
    render(<ReviewConversation round={failed} optimisticMessage={null} busy={false} onSubmit={vi.fn()} onSkip={vi.fn()} onCancel={vi.fn()} onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "重试评价" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("你的回答")).toBeNull();
  });
});
