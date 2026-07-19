import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewDiscussion } from "./ReviewDiscussion";
import type { ReviewAttempt } from "./reviewTypes";

class FakeEventSource {
  onopen = null;
  onerror = null;
  addEventListener() {}
  close() {}
}

const attempt = {
  id: "attempt-1", roundId: "round-1", ordinal: 1,
  questionSnapshot: { questionId: "q1", documentId: "d1", contentHash: "a".repeat(64), title: "MVCC", questionText: "Read View 如何判断可见性？", referenceAnswer: "比较上下界和活跃集合", topics: ["database"], difficulty: "medium", keyPoints: ["上下界", "活跃集合"], followUps: [] },
  answer: "我只提到了事务上下界", followUpAnswer: "补充了活跃事务集合",
  evaluation: { score: "partial", missing_key_points: ["可见性规则"], evidence: "没有说明具体可见性规则", mastery_suggestion: "partial" },
  masterySuggestion: "partial", skipped: false, status: "completed", evaluationErrorCode: null, evaluationStartedAt: null, evaluationCompletedAt: null, discussionSessionId: null, createdAt: "now", updatedAt: "now",
} as ReviewAttempt;

describe("ReviewDiscussion", () => {
  beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("opens with durable attempt context and calls the model only after user sends", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/settings/providers") return Response.json([]);
      if (url === "/api/agent/sessions/discussion-1" && (!init?.method || init.method === "GET")) return Response.json({ id: "discussion-1", workspaceId: "w1", kind: "review.discussion", title: "深入讨论：MVCC", status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "seed-1", messages: [], latestExecution: { id: "seed-1", sessionId: "discussion-1", status: "completed", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: "now" }, usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, contextUsage: { currentTokens: 32000, thresholdTokens: 89600, estimated: true }, latestWarning: null, currentAction: null });
      if (url === "/api/agent/sessions/discussion-1/executions" && init?.method === "POST") return Response.json({ id: "run-2", sessionId: "discussion-1", status: "running", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null }, { status: 202 });
      throw new Error(`unexpected ${url}`);
    });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ReviewDiscussion roundId="round-1" sessionId="discussion-1" attempt={attempt} defaultModelId="model-1" defaultReasoning="medium" onClose={vi.fn()} /></QueryClientProvider>);

    expect(await screen.findByText("本题上下文已准备好")).toBeInTheDocument();
    expect(screen.getByLabelText("本题讨论上下文")).toHaveTextContent("我只提到了事务上下界");
    expect(screen.queryByText("请结合本次回答解释遗漏点，并给一个迁移应用示例。")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "解释我遗漏的关键点" }));
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/agent/sessions/discussion-1/executions", expect.objectContaining({ method: "POST", body: JSON.stringify({ input: { message: "解释我遗漏的关键点" }, configuration: { providerModelId: "model-1", reasoningEffort: "medium" } }) })));
  });

  it("treats a durable assistant response as terminal even when legacy execution status is stale", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/settings/providers") return Response.json([]);
      if (url === "/api/agent/sessions/discussion-1") return Response.json({ id: "discussion-1", workspaceId: "w1", kind: "review.discussion", title: "深入讨论：MVCC", status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "run-1", messages: [{ id: "answer-1", executionId: "run-1", role: "assistant", content: "这里是完整解释", createdAt: "2026-07-19T10:00:05Z" }], executions: [{ id: "run-1", sessionId: "discussion-1", status: "completed", configuration: { providerModelId: "model-1", reasoningEffort: "medium" }, resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "2026-07-19T10:00:00Z", startedAt: "2026-07-19T10:00:00Z", finishedAt: "2026-07-19T10:00:05Z" }], latestExecution: { id: "run-1", sessionId: "discussion-1", status: "running", configuration: { providerModelId: "model-1", reasoningEffort: "medium" }, resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "2026-07-19T10:00:00Z", startedAt: "2026-07-19T10:00:00Z", finishedAt: null }, usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120, callCount: 1, estimatedCount: 0 }, contextUsage: { currentTokens: 32000, thresholdTokens: 89600, estimated: true }, contextCompacted: false, latestWarning: null, currentAction: null });
      throw new Error(`unexpected ${url}`);
    });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ReviewDiscussion roundId="round-1" sessionId="discussion-1" attempt={attempt} defaultModelId="model-1" onClose={vi.fn()} /></QueryClientProvider>);
    expect(await screen.findByText("这里是完整解释")).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "深入讨论记录" })).toHaveTextContent("耗时 5 秒");
    expect(screen.queryByRole("button", { name: "停止" })).toBeNull();
    expect(screen.getAllByText("讨论中").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("本题讨论上下文")).toHaveTextContent("32k / 89.6k");
    expect(screen.getByText("36%")).toBeInTheDocument();
  });

  it("keeps question context and evaluation summary mutually exclusive", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/settings/providers") return Response.json([]);
      if (url === "/api/agent/sessions/discussion-1") return Response.json({ id: "discussion-1", workspaceId: "w1", kind: "review.discussion", title: "深入讨论：MVCC", status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: null, messages: [], latestExecution: null, usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, contextUsage: { currentTokens: 0, thresholdTokens: 89600, estimated: true }, latestWarning: null, currentAction: null });
      throw new Error(`unexpected ${url}`);
    });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ReviewDiscussion roundId="round-1" sessionId="discussion-1" attempt={attempt} defaultModelId="model-1" onClose={vi.fn()} /></QueryClientProvider>);
    await screen.findByText("本题上下文已准备好");
    const question = screen.getByText("本题上下文").closest("details")!;
    const evaluation = screen.getByText("评价摘要").closest("details")!;
    const header = screen.getByText("单题深入讨论").closest("header")!;
    expect(header.firstElementChild).toHaveClass("review-discussion__title");
    expect(header.lastElementChild).toHaveClass("review-discussion__header-actions");
    expect(evaluation).toHaveClass("review-discussion__evaluation");
    expect(screen.getByLabelText("建议问题").querySelectorAll("button")).toHaveLength(3);
    expect(question).toHaveAttribute("open");
    expect(evaluation).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("评价摘要"));
    expect(question).not.toHaveAttribute("open");
    expect(evaluation).toHaveAttribute("open");
  });
});
