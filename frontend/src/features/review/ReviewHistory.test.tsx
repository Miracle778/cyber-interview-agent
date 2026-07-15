import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewHistory } from "./ReviewHistory";
import type { ReviewRound } from "./reviewTypes";

function round(status: ReviewRound["status"], currentIndex: number): ReviewRound {
  return {
    id: status,
    workspaceId: "w1",
    sessionId: `s-${status}`,
    executionId: `e-${status}`,
    settings: {
      mode: "random-mixed",
      question_count: 3,
      topics: [],
      difficulties: [],
      allow_follow_up: true,
      answer_model_id: "model",
      reasoning_effort: "medium",
      seed: 1,
    },
    status,
    currentIndex,
    questionCount: 3,
    currentQuestion: null,
    currentInput: null,
    attempts: [],
    messages: [],
    reports: [],
    usage: {
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      callCount: 0,
      estimatedCount: 0,
    },
    executionStatus: null,
    createdAt: "2026-07-15T00:00:00Z",
    updatedAt: "2026-07-15T00:00:00Z",
    completedAt: status === "completed" ? "2026-07-15T00:00:00Z" : null,
  };
}

describe("ReviewHistory", () => {
  afterEach(cleanup);

  it("does not describe the current waiting question as completed", () => {
    render(
      <ReviewHistory
        rounds={[round("waiting_for_input", 0), round("completed", 3)]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("第 1/3 题")).toBeInTheDocument();
    expect(screen.getByText("3/3 已完成")).toBeInTheDocument();
    expect(screen.queryByText("0/3 已完成")).toBeNull();
  });
});
