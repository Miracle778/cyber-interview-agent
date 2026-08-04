import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveConversation } from "./RetrospectiveConversation";
import * as api from "./retrospectiveApi";
import * as agentApi from "../agent/agentApi";

vi.mock("./retrospectiveApi", () => ({
  getRetrospectiveConversation: vi.fn(),
  sendRetrospectiveMessage: vi.fn(),
  stopRetrospectiveMessage: vi.fn(),
  decideRetrospectiveCorrection: vi.fn(),
}));

vi.mock("../agent/agentApi", () => ({ getAgentSession: vi.fn() }));

const proposal = {
  id: "proposal-1",
  retrospectiveId: "retro-1",
  chatMessageId: "message-2",
  proposalType: "question_text_correction" as const,
  targetQuestionId: "question-1",
  sourceCleanupVersionId: "cleanup-1",
  sourceAnalysisRunId: "run-1",
  before: { questionText: "缓存怎么做？" },
  after: { questionText: "如何保证缓存与数据库最终一致？" },
  rationale: "转写后的题意不准确",
  expectedVersion: 1,
  status: "pending" as const,
  resultingCleanupVersionId: null,
  resultingAnalysisRunId: null,
  version: 1,
  createdAt: "now",
  updatedAt: "now",
};

function renderConversation(onCorrectionConfirmed = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><RetrospectiveConversation workspaceId="w1" retrospectiveId="retro-1" selectedQuestionId="question-1" selectedQuestionText="请做一下自我介绍" onClose={vi.fn()} onCorrectionConfirmed={onCorrectionConfirmed} /></QueryClientProvider>);
  return onCorrectionConfirmed;
}

beforeEach(() => {
  vi.mocked(agentApi.getAgentSession).mockResolvedValue({
    id: "session-1",
    workspaceId: "w1",
    kind: "interview_retrospective_chat",
    title: "复盘讨论：字节云",
    status: "active",
    createdAt: "2026-08-03T09:00:00Z",
    updatedAt: "2026-08-03T10:00:00Z",
    latestExecutionId: "execution-1",
    latestExecutionStatus: "completed",
    usage: { inputTokens: 800, outputTokens: 400, totalTokens: 1200, callCount: 1, estimatedCount: 0 },
    contextUsage: { currentTokens: 1800, thresholdTokens: 32000, estimated: false },
    contextCompacted: false,
    latestWarning: null,
    messages: [],
    executions: [],
    latestExecution: {
      id: "execution-1",
      sessionId: "session-1",
      status: "completed",
      configuration: { providerModelId: "model-1", reasoningEffort: "none" },
      resumeCount: 0,
      errorCode: null,
      errorMessage: null,
      createdAt: "2026-08-03T09:59:50Z",
      startedAt: "2026-08-03T09:59:50Z",
      finishedAt: "2026-08-03T10:00:00Z",
    },
    currentAction: null,
  });
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("RetrospectiveConversation", () => {
  it("shows explicit before/after and confirms a pending correction", async () => {
    vi.mocked(api.getRetrospectiveConversation).mockResolvedValue({
      sessionId: "session-1",
      messages: [{ id: "message-2", executionId: "execution-1", role: "assistant", content: "纠正建议", messageKind: "proposal_card", payload: {}, createdAt: "now" }],
      proposals: [proposal],
      latestExecution: { id: "execution-1", status: "completed", errorCode: null, createdAt: "now", finishedAt: "now" },
    });
    vi.mocked(api.decideRetrospectiveCorrection).mockResolvedValue({ ...proposal, status: "confirmed", version: 2 });
    const confirmed = renderConversation();

    expect(await screen.findByText("缓存怎么做？", { exact: false })).toBeVisible();
    expect(screen.getByText("如何保证缓存与数据库最终一致？", { exact: false })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /确认并重新分析/ }));

    await waitFor(() => expect(api.decideRetrospectiveCorrection).toHaveBeenCalledWith("w1", "retro-1", "proposal-1", "confirmed"));
    expect(confirmed).toHaveBeenCalled();
  });

  it("sends the current question context through the shared composer", async () => {
    vi.mocked(api.getRetrospectiveConversation).mockResolvedValue({ sessionId: "session-1", messages: [], proposals: [], latestExecution: null });
    vi.mocked(api.sendRetrospectiveMessage).mockResolvedValue({ executionId: "execution-2", status: "running" });
    renderConversation();

    const textbox = await screen.findByRole("textbox", { name: "发送给复盘助手" });
    fireEvent.change(textbox, { target: { value: "为什么这里是高风险？" } });
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter" });

    await waitFor(() => expect(api.sendRetrospectiveMessage).toHaveBeenCalledWith("w1", "retro-1", "为什么这里是高风险？", "question-1"));
  });

  it("uses the retrospective assistant identity and exposes the standard conversation context", async () => {
    vi.mocked(api.getRetrospectiveConversation).mockResolvedValue({
      sessionId: "session-1",
      messages: [{ id: "message-1", executionId: "execution-1", role: "assistant", content: "先建立全局认知框架。", messageKind: "text", payload: {}, createdAt: "2026-08-03T10:00:00Z" }],
      proposals: [],
      latestExecution: { id: "execution-1", status: "completed", errorCode: null, createdAt: "2026-08-03T09:59:50Z", finishedAt: "2026-08-03T10:00:00Z" },
    });
    renderConversation();

    expect(await screen.findByText("复盘助手")).toBeVisible();
    expect(screen.queryByText("画像助手")).not.toBeInTheDocument();
    expect(screen.getByLabelText("运行状态：可继续对话")).toBeVisible();
    expect(screen.getByText("本次讨论已完成")).toBeVisible();

    const contextAside = screen.getByRole("complementary", { name: "本次依据" });
    expect(within(contextAside).getByRole("heading", { name: "运行状态" })).toBeVisible();
    expect(within(contextAside).getByText("请做一下自我介绍")).toBeVisible();
    expect(within(contextAside).getByText(/纠正建议需要你确认后才会修改复盘/)).toBeVisible();
    expect(within(contextAside).getByText("10 秒")).toBeVisible();
    fireEvent.click(within(contextAside).getByText("技术详情"));
    expect(within(contextAside).getByText("1.2k")).toBeVisible();
  });

  it.each([
    ["running", "正在处理"],
    ["waiting_for_input", "等待你继续"],
    ["waiting_for_approval", "等待你确认"],
    ["failed", "需要重试"],
    ["interrupted", "处理已中断"],
    ["cancelled", "已停止"],
  ])("shows a user-facing %s execution status in the title bar", async (status, label) => {
    vi.mocked(api.getRetrospectiveConversation).mockResolvedValue({
      sessionId: "session-1",
      messages: [],
      proposals: [],
      latestExecution: { id: "execution-1", status, errorCode: null, createdAt: "2026-08-03T10:00:00Z", finishedAt: null },
    });
    renderConversation();

    expect(await screen.findByLabelText(`运行状态：${label}`)).toBeVisible();
  });

  it("fills rather than sends a starter question", async () => {
    vi.mocked(api.getRetrospectiveConversation).mockResolvedValue({ sessionId: "session-1", messages: [], proposals: [], latestExecution: null });
    renderConversation();

    fireEvent.click(await screen.findByRole("button", { name: "解释这道题的分析依据" }));
    expect(screen.getByRole("textbox", { name: "发送给复盘助手" })).toHaveValue("解释这道题的分析依据");
    expect(api.sendRetrospectiveMessage).not.toHaveBeenCalled();
  });
});
