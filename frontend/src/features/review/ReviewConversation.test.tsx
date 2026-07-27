import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

function renderConversation(props: Partial<React.ComponentProps<typeof ReviewConversation>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["providers"], [{ id: "p1", name: "火山", enabled: true, models: [{ id: "m1", displayName: "GLM", enabled: true }, { id: "m2", displayName: "Doubao", enabled: true }] }]);
  return render(<QueryClientProvider client={client}><ReviewConversation round={round} optimisticMessage={null} busy={false} onSubmit={vi.fn()} onSkip={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} {...props} /></QueryClientProvider>);
}

describe("ReviewConversation", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });
  it("renders ordered messages and a named evaluation stage without chain of thought", () => {
    renderConversation();
    const log = screen.getByRole("log", { name: "复习对话" });
    expect(log).toHaveTextContent("Explain MVCC");
    expect(log).toHaveTextContent("multiple versions");
    expect(log).toHaveTextContent("复习助手");
    expect(log).not.toHaveTextContent("面试官");
    expect(log).toHaveTextContent("理解本次回答");
    expect(log).toHaveTextContent("评价结果校验完成后会一次展示");
    expect(log).not.toHaveTextContent("思维链");
    expect(screen.getByText("multiple versions").closest("article")).toHaveClass("review-chat-message--user");
    expect(within(log).getByText("Explain MVCC").closest("article")).toHaveClass("review-chat-message--agent");
  });

  it("shows durable stage progress and a live processing duration beside the assistant", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-19T10:00:03Z"));
    const evaluating = {
      ...round,
      attempts: [{ ...round.attempts[0], evaluationStartedAt: "2026-07-19T10:00:00Z" }],
    } as ReviewRound;

    renderConversation({ round: evaluating, evaluationStage: "checking_key_points" });

    const progress = screen.getByRole("status", { name: "回答评价进度" });
    expect(progress).toHaveTextContent("处理中 3 秒");
    expect(progress).toHaveTextContent("对照必答方向");
    expect(within(progress).getByText("回答已保存").closest("li")).toHaveAttribute("data-state", "completed");
    const activeStep = within(progress).getAllByText("对照必答方向")
      .map((item) => item.closest("li"))
      .find(Boolean);
    expect(activeStep).toHaveAttribute("data-state", "active");
    expect(within(progress).getByText("生成反馈与下一步").closest("li")).toHaveAttribute("data-state", "pending");
  });

  it("shows the real per-attempt processing duration beside an evaluation reply", () => {
    const evaluated = {
      ...round,
      attempts: [{ ...round.attempts[0], status: "completed", evaluationStartedAt: "2026-07-19T10:00:00Z", evaluationCompletedAt: "2026-07-19T10:00:06Z" }],
      messages: [...round.messages, { id: "m3", executionId: "e1", role: "assistant", content: "本题评价已完成。", messageKind: "evaluation_card", payload: { attemptId: "a1", evaluation: { score: "partial", evidence: "还需要补充可见性规则" } }, createdAt: "2026-07-19T10:00:06Z" }],
    } as ReviewRound;
    renderConversation({ round: evaluated });
    expect(screen.getByRole("log", { name: "复习对话" })).toHaveTextContent("耗时 6 秒");
  });

  it("labels a revealed answer as a local zero-token response", () => {
    const revealed = {
      ...round,
      messages: [...round.messages, {
        id: "m3",
        executionId: "e1",
        role: "assistant",
        content: "参考答案：多个版本并发控制",
        messageKind: "review_prompt",
        payload: { auxiliary: true, intent: "reveal_answer" },
        createdAt: "2026-07-19T10:00:06Z",
      }],
    } as ReviewRound;
    renderConversation({ round: revealed });
    const answer = screen.getByText("参考答案：多个版本并发控制").closest("article")!;
    expect(within(answer).getByText("题库参考答案")).toBeInTheDocument();
    expect(within(answer).getByText("本地读取 · 0 Token")).toBeInTheDocument();
  });

  it("keeps the answer composer after the scrollable conversation", () => {
    const waiting = { ...round, currentInput: { id: "i1", roundId: "r1", ordinal: 1, kind: "follow_up", prompt: "补充一下", version: 1, status: "pending", createdAt: "now", resolvedAt: null } } as ReviewRound;
    const view = renderConversation({ round: waiting });
    const scoped = within(view.container);
    const log = scoped.getByRole("log", { name: "复习对话" });
    const input = scoped.getByRole("textbox", { name: "补充回答" });
    expect(log.compareDocumentPosition(input.closest("footer")!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(scoped.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(input.closest("footer")).toHaveClass("curation-composer", "review-round-composer");
    expect(scoped.getByText("火山 / GLM · 默认思考")).toBeInTheDocument();
    fireEvent.click(scoped.getByText("火山 / GLM · 默认思考"));
    expect(scoped.getByRole("combobox", { name: "评价模型" })).toBeInTheDocument();
    expect(scoped.getByRole("button", { name: "跳过" })).toBeInTheDocument();
  });

  it("submits the selected model and reasoning for this answer", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    const waiting = { ...round, currentInput: { id: "i1", roundId: "r1", ordinal: 1, kind: "answer", prompt: "继续回答", version: 1, status: "pending", createdAt: "now", resolvedAt: null } } as ReviewRound;
    renderConversation({ round: waiting, onSubmit: submit });
    fireEvent.click(screen.getByText("火山 / GLM · 默认思考"));
    fireEvent.change(screen.getByRole("combobox", { name: "评价模型" }), { target: { value: "m2" } });
    fireEvent.change(screen.getByRole("combobox", { name: "评价思考强度" }), { target: { value: "high" } });
    fireEvent.change(screen.getByRole("textbox", { name: "你的回答" }), { target: { value: "我的回答" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(submit).toHaveBeenCalledWith("我的回答", { providerModelId: "m2", reasoningEffort: "high" });
  });

  it("offers retry for a failed evaluation without asking for the answer again", () => {
    const retry = vi.fn();
    const failed = { ...round, attempts: [{ ...round.attempts[0], status: "evaluation_failed", evaluationErrorCode: "provider_error" }] } as ReviewRound;
    renderConversation({ round: failed, onRetry: retry });
    fireEvent.click(screen.getByRole("button", { name: "重试评价" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("你的回答")).toBeNull();
  });
});
