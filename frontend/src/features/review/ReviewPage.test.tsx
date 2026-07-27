import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ReviewPage } from "./ReviewPage";
import type { ActiveQuestion, ReviewRound } from "./reviewTypes";

class FakeEventSource {
  onopen = null;
  onerror = null;
  addEventListener() {}
  close() {}
}

const workspace: WorkspaceConfig = { id: "w1", workspacePath: "/tmp/demo", vaultPath: "/tmp/demo/vault" };
const waitingRound: ReviewRound = {
  id: "round-1", workspaceId: "w1", sessionId: "session-1", executionId: "run-1",
  settings: { topics: [], difficulties: ["medium"], mode: "random-mixed", question_count: 2, allow_follow_up: true, seed: 1, answer_model_id: "model-1", reasoning_effort: "medium" },
  status: "waiting_for_input", executionStatus: "waiting_for_input", currentIndex: 0, questionCount: 2,
  currentQuestion: { id: "q1", title: "MVCC", questionText: "Read View 如何判断可见性？", topics: ["database"], difficulty: "medium" },
  currentInput: { id: "input-1", roundId: "round-1", ordinal: 1, kind: "answer", prompt: "Read View 如何判断可见性？", version: 1, status: "pending", createdAt: "now", resolvedAt: null },
  attempts: [], reports: [], usage: { inputTokens: 12, outputTokens: 4, totalTokens: 16, callCount: 1, estimatedCount: 0 }, contextUsage: { currentTokens: 32000, thresholdTokens: 89600, estimated: true }, createdAt: "now", updatedAt: "now", completedAt: null,
  messages: [],
};

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider></MemoryRouter>;
}

function activeQuestions(count: number): ActiveQuestion[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `q-${index}`,
    draftId: `d-${index}`,
    publicationId: `p-${index}`,
    publishedAt: "now",
    title: `Question ${index + 1}`,
    questionText: "Question body",
    referenceAnswer: "Reference answer",
    topics: ["database"],
    difficulty: "medium",
    keyPoints: ["point"],
    followUps: [],
  }));
}

function mockApi(rounds: ReviewRound[], questions: ActiveQuestion[] = []) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/review/rounds/round-1/retry" && init?.method === "POST") return Response.json({ ...rounds[0], executionStatus: "running" }, { status: 202 });
    if (url.includes("/api/review/rounds?")) return Response.json(rounds);
    if (url === "/api/review/rounds/round-1") return Response.json(rounds[0]);
    if (url.includes("/api/review/questions?")) return Response.json(questions);
    if (url === "/api/settings/providers") return Response.json([]);
    if (url.includes("/model-bindings")) return Response.json({ workspaceId: "w1", bindings: {} });
    if (url.includes("/api/agent/sessions/session-1")) return Response.json({});
    if (url.includes("/api/agent/actions?")) return Response.json([]);
    throw new Error(`unexpected ${url}`);
  });
}

describe("R2 ReviewPage", () => {
  beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("separates question curation and review as primary entries", async () => {
    mockApi([]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    const navigation = await screen.findByRole("navigation", { name: "复习工作台入口" });
    const practiceEntry = within(navigation).getByRole("button", { name: /开始复习/ });
    const catalogEntry = within(navigation).getByRole("button", { name: /题库整理/ });
    expect(practiceEntry).toHaveAttribute("aria-current", "page");
    expect(practiceEntry.compareDocumentPosition(catalogEntry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByRole("button", { name: "创建复习" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "题库尚未准备好" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "去题库整理" }));
    expect(await screen.findByRole("heading", { name: "题库整理" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建复习" })).toBeNull();
  });

  it("defaults to history and enters a selected round without showing HITL", async () => {
    mockApi([waitingRound]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    expect(await screen.findByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "当前复习轮次" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("region", { name: "当前复习轮次" })).toHaveTextContent("Read View 如何判断可见性？");
    const feedback = screen.getByLabelText("本题反馈");
    expect(feedback).toHaveTextContent("model-1");
    expect(feedback).toHaveTextContent("中等思考");
    expect(feedback).toHaveTextContent("16");
    expect(feedback).toHaveTextContent("32k / 90k");
    expect(feedback).toHaveTextContent("36%");
    expect(screen.getByRole("navigation", { name: "本轮题目进度" })).toHaveTextContent("MVCC");
    expect(screen.queryByRole("navigation", { name: "复习轮次历史" })).not.toBeInTheDocument();
    expect(screen.queryByText("待确认操作")).toBeNull();
  });

  it("shows completed results without reopening setup", async () => {
    mockApi([{ ...waitingRound, status: "completed", executionStatus: "completed", currentQuestion: null, currentInput: null, completedAt: "later" }]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    await screen.findByRole("heading", { name: "复习历史" });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByText("本轮复习结果")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "复习报告" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "会话回放" })).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });

  it("shows a recovery action instead of a broken active conversation", async () => {
    const failed = { ...waitingRound, executionStatus: "failed", currentInput: null } as ReviewRound;
    const fetch = mockApi([failed]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("status", { name: "复习轮次需要恢复" })).toHaveTextContent("回答和评价记录都已保留");
    fireEvent.click(screen.getByRole("button", { name: "恢复本轮" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/review/rounds/round-1/retry", expect.objectContaining({ method: "POST" })));
  });

  it("shows an explicit ended state for an empty cancelled round", async () => {
    const ended = { ...waitingRound, status: "cancelled", executionStatus: "cancelled", currentQuestion: null, currentInput: null } as ReviewRound;
    mockApi([ended]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("status", { name: "复习轮次已结束" })).toHaveTextContent("尚未产生回答记录");
  });

  it("opens and closes creation as a distinct panel", async () => {
    mockApi([], activeQuestions(10));
    render(<ReviewPage workspace={workspace} />, { wrapper });
    const createButton = await screen.findByRole("button", { name: "创建复习" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    expect(await screen.findByText("创建复习轮次")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回历史" }));
    expect(await screen.findByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });

  it("keeps a large topic catalog compact until the user expands or searches it", async () => {
    const questions = activeQuestions(24).map((question, index) => ({
      ...question,
      topics: [`主题 ${String(index + 1).padStart(2, "0")}`],
    }));
    mockApi([], questions);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    const createButton = await screen.findByRole("button", { name: "创建复习" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);

    expect(await screen.findByRole("button", { name: "展开全部（24）" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(18);
    expect(screen.queryByRole("checkbox", { name: "主题 24" })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "搜索复习主题" }), { target: { value: "主题 24" } });
    expect(screen.getByRole("checkbox", { name: "主题 24" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });
});
