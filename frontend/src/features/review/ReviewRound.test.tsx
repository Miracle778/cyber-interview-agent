import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewRound } from "./ReviewRound";
import type { ReviewRound as RoundValue } from "./reviewTypes";

const round: RoundValue = {
  id: "r", workspaceId: "w", sessionId: "s", executionId: "e",
  settings: { topics: [], difficulties: ["medium"], mode: "random-mixed", question_count: 1, allow_follow_up: true, seed: 1, answer_model_id: "m", reasoning_effort: "none" },
  status: "waiting_for_input", executionStatus: "waiting_for_input", currentIndex: 0, questionCount: 1,
  currentQuestion: { id: "q", title: "缓存", questionText: "缓存穿透是什么？", topics: ["cache"], difficulty: "medium" },
  currentInput: { id: "i", roundId: "r", ordinal: 1, kind: "answer", prompt: "缓存穿透是什么？", version: 1, status: "pending", createdAt: "now", resolvedAt: null },
  attempts: [], reports: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "now", updatedAt: "now", completedAt: null,
};

describe("ReviewRound", () => {
  afterEach(cleanup);
  it("keeps typed input when the server submission fails", async () => {
    const submit = vi.fn().mockRejectedValue(new Error("network"));
    render(<ReviewRound round={round} onSubmit={submit} onSkip={vi.fn()} onCancel={vi.fn()} busy={false} />);
    fireEvent.change(screen.getByLabelText("你的回答"), { target: { value: "缓存空值" } });
    fireEvent.click(screen.getByRole("button", { name: "发送回答" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("缓存空值"));
    expect(screen.getByLabelText("你的回答")).toHaveValue("缓存空值");
  });
});
