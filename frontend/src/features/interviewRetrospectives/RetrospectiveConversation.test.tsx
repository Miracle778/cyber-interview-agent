import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveConversation } from "./RetrospectiveConversation";
import * as api from "./retrospectiveApi";

vi.mock("./retrospectiveApi", () => ({
  getRetrospectiveConversation: vi.fn(),
  sendRetrospectiveMessage: vi.fn(),
  stopRetrospectiveMessage: vi.fn(),
  decideRetrospectiveCorrection: vi.fn(),
}));

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
  render(<QueryClientProvider client={client}><RetrospectiveConversation workspaceId="w1" retrospectiveId="retro-1" selectedQuestionId="question-1" onClose={vi.fn()} onCorrectionConfirmed={onCorrectionConfirmed} /></QueryClientProvider>);
  return onCorrectionConfirmed;
}

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
});
