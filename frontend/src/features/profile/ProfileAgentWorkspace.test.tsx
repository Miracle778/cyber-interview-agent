import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";

const mocks = vi.hoisted(() => ({
  listSessions: vi.fn(),
  getSession: vi.fn(),
  getUnifiedProfile: vi.fn(),
  deleteSession: vi.fn(),
  live: {
    status: "disconnected",
    events: [] as Array<Record<string, unknown>>,
    executionError: null,
    streamingByExecution: {} as Record<string, unknown>,
    executionStateById: {} as Record<string, string>,
  },
}));

vi.mock("./profileApi", () => ({ listProfileSessions: mocks.listSessions, createProfileSession: vi.fn(), getUnifiedProfile: mocks.getUnifiedProfile }));
vi.mock("../agent/agentApi", () => ({
  getAgentSession: mocks.getSession,
  startAgentExecution: vi.fn(),
  cancelAgentExecution: vi.fn(),
  deleteAgentSession: mocks.deleteSession,
}));
vi.mock("../agent/useAgentEvents", () => ({ useAgentEvents: () => mocks.live }));

describe("ProfileAgentWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    mocks.listSessions.mockReset();
    mocks.getSession.mockReset();
    mocks.deleteSession.mockReset();
    mocks.getUnifiedProfile.mockReset();
    mocks.listSessions.mockResolvedValue([]);
    mocks.deleteSession.mockResolvedValue(undefined);
    mocks.getUnifiedProfile.mockResolvedValue({
      workspaceId: "w1", profileVersion: null, summary: null, directions: [],
      primaryDirectionClaimId: null, presentationVersion: 0, highlights: [],
      experiences: [], projects: [], skills: [], education: [], certifications: [],
      achievements: [], links: [], actionableGaps: [], pendingCount: 0, isUsable: false,
    });
    mocks.live.status = "disconnected";
    mocks.live.events = [];
    mocks.live.streamingByExecution = {};
    mocks.live.executionStateById = {};
  });

  it("offers a clear empty state and one primary start action", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "开始使用画像助手" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始新对话" })).toBeEnabled();
  });

  it("lets durable interrupted state end stale SSE running UI", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "个人画像对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "个人画像对话",
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

    const composer = await screen.findByPlaceholderText("例如：检查我的项目经历是否缺少职责、方案或结果");
    expect(screen.getByRole("button", { name: "画像助手对话" })).toBeInTheDocument();
    expect(screen.queryByText("个人画像对话")).toBeNull();
    expect(screen.queryByRole("button", { name: "停止" })).not.toBeInTheDocument();
    expect(composer).toBeEnabled();
    fireEvent.change(composer, { target: { value: "继续" } });
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
  });

  it("permanently deletes an old conversation without touching profile data", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s-old", workspaceId: "w1", kind: "profile.chat", title: "旧简历讨论",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: null,
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s-old", workspaceId: "w1", kind: "profile.chat", title: "旧简历讨论",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: null,
      messages: [], executions: [], currentAction: null, latestWarning: null,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
      latestExecution: null,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "永久删除会话 旧简历讨论" }));

    await waitFor(() => expect(mocks.deleteSession).toHaveBeenCalledWith("s-old", true));
    expect(await screen.findByRole("heading", { name: "开始使用画像助手" })).toBeInTheDocument();
  });

  it("does not render completed streaming text beside the persisted assistant message", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
      messages: [{ id: "m1", executionId: "r1", role: "assistant", content: "资料检查完成", createdAt: "now" }],
      executions: [], currentAction: null, latestWarning: null,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 1, estimatedCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
      latestExecution: {
        id: "r1", sessionId: "s1", status: "completed", resumeCount: 0,
        errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: "now",
      },
    });
    mocks.live.streamingByExecution = { r1: { text: "资料检查完成", status: "completed" } };

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);

    expect(await screen.findAllByText("资料检查完成")).toHaveLength(1);
  });

  it("hides raw model chunks while a structured profile change is being planned", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
      messages: [{ id: "m1", executionId: "r1", role: "user", content: "把 Docker 熟练程度改为熟练", createdAt: "now" }],
      executions: [], currentAction: null, latestWarning: null,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 1, estimatedCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
      latestExecution: {
        id: "r1", sessionId: "s1", status: "running", resumeCount: 0,
        errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null,
      },
    });
    mocks.live.executionStateById = { r1: "running" };
    mocks.live.streamingByExecution = { r1: { text: "内部 Claim ID 和 Evidence 分析", status: "running" } };

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);

    expect(await screen.findByRole("status")).toHaveTextContent("正在整理可确认的结果");
    expect(screen.queryByText(/内部 Claim ID/)).toBeNull();
  });

  it("refreshes session detail when a capped event list advances", async () => {
    mocks.listSessions.mockResolvedValue([{
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
    }]);
    mocks.getSession.mockResolvedValue({
      id: "s1", workspaceId: "w1", kind: "profile.chat", title: "简历助手对话",
      status: "active", createdAt: "now", updatedAt: "now", latestExecutionId: "r1",
      messages: [], executions: [], currentAction: null, latestWarning: null,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
      latestExecution: null,
    });
    mocks.live.events = [{ id: 100, type: "assistant.delta", sessionId: "s1", executionId: "r1", timestamp: "now", payload: { text: "处理中" } }];

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);
    await waitFor(() => expect(mocks.getSession).toHaveBeenCalled());
    const callsBeforeAdvance = mocks.getSession.mock.calls.length;

    mocks.live.events = [{ id: 101, type: "execution.completed", sessionId: "s1", executionId: "r1", timestamp: "now", payload: {} }];
    view.rerender(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);

    await waitFor(() => expect(mocks.getSession.mock.calls.length).toBeGreaterThan(callsBeforeAdvance));
  });
});
