import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";

const mocks = vi.hoisted(() => ({
  listSessions: vi.fn(),
  getSession: vi.fn(),
  live: {
    status: "disconnected",
    events: [] as Array<Record<string, unknown>>,
    executionError: null,
    streamingByExecution: {} as Record<string, unknown>,
    executionStateById: {} as Record<string, string>,
  },
}));

vi.mock("./profileApi", () => ({ listProfileSessions: mocks.listSessions, createProfileSession: vi.fn() }));
vi.mock("../agent/agentApi", () => ({
  getAgentSession: mocks.getSession,
  startAgentExecution: vi.fn(),
  cancelAgentExecution: vi.fn(),
}));
vi.mock("../agent/useAgentEvents", () => ({ useAgentEvents: () => mocks.live }));

describe("ProfileAgentWorkspace", () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.listSessions.mockReset();
    mocks.getSession.mockReset();
    mocks.listSessions.mockResolvedValue([]);
    mocks.live.status = "disconnected";
    mocks.live.events = [];
    mocks.live.streamingByExecution = {};
    mocks.live.executionStateById = {};
  });

  it("offers a clear empty state and one primary start action", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "开始画像会话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeEnabled();
  });

  it("lets durable interrupted state end stale SSE running UI", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "画像会话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "画像会话",
      status: "interrupted", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
      messages: [], executions: [], currentAction: null, latestWarning: null,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 1, estimatedCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
      latestExecution: {
        id: "r1", sessionId: "s1", status: "interrupted", resumeCount: 0,
        errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: "now",
      },
    });
    mocks.live.executionStateById = { r1: "running" };
    mocks.live.events = [{
      id: 1, type: "agent.tool.started", sessionId: "s1", executionId: "r1",
      timestamp: "now", payload: { toolCallId: "c1", toolName: "search_personal_materials" },
    }];

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);

    const composer = await screen.findByPlaceholderText("询问画像，或描述需要评估、修改的内容…");
    expect(screen.queryByRole("button", { name: "停止" })).not.toBeInTheDocument();
    expect(composer).toBeEnabled();
    fireEvent.change(composer, { target: { value: "继续" } });
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
  });
});
