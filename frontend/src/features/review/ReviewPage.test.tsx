import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ReviewPage } from "./ReviewPage";
import type { ReviewRound } from "./reviewTypes";

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
  attempts: [], reports: [], usage: { inputTokens: 12, outputTokens: 4, totalTokens: 16, callCount: 1, estimatedCount: 0 }, createdAt: "now", updatedAt: "now", completedAt: null,
  messages: [],
};

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider></MemoryRouter>;
}

function mockApi(rounds: ReviewRound[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/review/rounds?")) return Response.json(rounds);
    if (url === "/api/review/rounds/round-1") return Response.json(rounds[0]);
    if (url.includes("/api/review/questions?")) return Response.json([]);
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
    expect(within(navigation).getByRole("button", { name: /题库整理/ })).toBeInTheDocument();
    expect(within(navigation).getByRole("button", { name: /开始复习/ })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("button", { name: "创建复习" })).toBeInTheDocument();

    fireEvent.click(within(navigation).getByRole("button", { name: /题库整理/ }));
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
    expect(screen.getByLabelText("轮次运行状态")).toHaveTextContent("model-1");
    expect(screen.getByLabelText("轮次运行状态")).toHaveTextContent("medium");
    expect(screen.getByLabelText("轮次运行状态")).toHaveTextContent("16 tokens");
    expect(screen.queryByText("待确认操作")).toBeNull();
  });

  it("shows completed results without reopening setup", async () => {
    mockApi([{ ...waitingRound, status: "completed", executionStatus: "completed", currentQuestion: null, currentInput: null, completedAt: "later" }]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    await screen.findByRole("heading", { name: "复习历史" });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByText("本轮复习结果")).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });

  it("opens and closes creation as a distinct panel", async () => {
    mockApi([]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: "创建复习" }));
    expect(await screen.findByText("创建复习轮次")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回历史" }));
    expect(await screen.findByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });
});
