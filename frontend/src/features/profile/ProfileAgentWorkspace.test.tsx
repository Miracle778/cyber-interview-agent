import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";

const mocks = vi.hoisted(() => ({
  activeSessions: [] as Array<Record<string, unknown>>,
  archivedSessions: [] as Array<Record<string, unknown>>,
  listSessions: vi.fn(),
  createSession: vi.fn(),
  getSession: vi.fn(),
  getUnifiedProfile: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  restoreSession: vi.fn(),
  startExecution: vi.fn(),
  live: {
    status: "disconnected",
    events: [] as Array<Record<string, unknown>>,
    executionError: null,
    streamingByExecution: {} as Record<string, unknown>,
    executionStateById: {} as Record<string, string>,
  },
}));

vi.mock("./profileApi", () => ({
  listProfileSessions: mocks.listSessions,
  createProfileSession: mocks.createSession,
  getUnifiedProfile: mocks.getUnifiedProfile,
}));
vi.mock("../agent/agentApi", () => ({
  getAgentSession: mocks.getSession,
  startAgentExecution: mocks.startExecution,
  cancelAgentExecution: vi.fn(),
  deleteAgentSession: mocks.deleteSession,
  renameAgentSession: mocks.renameSession,
  restoreAgentSession: mocks.restoreSession,
}));
vi.mock("../agent/useAgentEvents", () => ({ useAgentEvents: () => mocks.live }));
vi.mock("../settings/settingsApi", () => ({ listProviders: vi.fn().mockResolvedValue([]) }));

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ProfileAgentWorkspace workspaceId="w1" /></QueryClientProvider>);
}

function session(id = "s1", title = "个人画像对话") {
  return { id, workspaceId: "w1", kind: "profile.manage", title, status: "active", createdAt: "2026-07-24T10:00:00Z", updatedAt: "2026-07-24T10:00:00Z", latestExecutionId: null };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...session(),
    messages: [],
    executions: [],
    currentAction: null,
    latestWarning: null,
    usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 },
    contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false },
    latestExecution: null,
    ...overrides,
  };
}

describe("ProfileAgentWorkspace", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.activeSessions = [];
    mocks.archivedSessions = [];
    mocks.listSessions.mockImplementation((_workspaceId, _signal, deletedOnly = false) => Promise.resolve(deletedOnly ? mocks.archivedSessions : mocks.activeSessions));
    mocks.getUnifiedProfile.mockResolvedValue({
      workspaceId: "w1", profileVersion: null, summary: null, directions: [],
      primaryDirectionClaimId: null, presentationVersion: 0, highlights: [],
      experiences: [], projects: [], skills: [], education: [], certifications: [],
      achievements: [], links: [], actionableGaps: [], pendingCount: 0, isUsable: false,
    });
    mocks.deleteSession.mockResolvedValue(undefined);
    mocks.restoreSession.mockResolvedValue(session());
    mocks.live.status = "disconnected";
    mocks.live.events = [];
    mocks.live.streamingByExecution = {};
    mocks.live.executionStateById = {};
  });

  it("starts on a searchable conversation-record page", async () => {
    renderWorkspace();
    expect(await screen.findByRole("heading", { name: "会话记录" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("搜索标题或最近消息")).toBeEnabled();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeEnabled();
  });

  it("opens a selected conversation and lets durable terminal state beat stale SSE", async () => {
    mocks.activeSessions = [session()];
    mocks.getSession.mockResolvedValue(detail({
      latestExecutionId: "r1",
      latestExecution: {
        id: "r1", sessionId: "s1", status: "interrupted", resumeCount: 0,
        errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: "now",
      },
    }));
    mocks.live.executionStateById = { r1: "running" };

    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /画像助手对话/ }));

    expect(await screen.findByPlaceholderText("例如：检查我的项目经历是否缺少职责、方案或结果")).toBeEnabled();
    expect(await screen.findAllByText("处理已中断")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "停止" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回会话记录" })).toBeEnabled();
  });

  it("archives from the record page instead of permanently deleting immediately", async () => {
    mocks.activeSessions = [session("s-old", "旧简历讨论")];
    renderWorkspace();

    fireEvent.click(await screen.findByRole("button", { name: "归档" }));

    await waitFor(() => expect(mocks.deleteSession).toHaveBeenCalledWith("s-old", false));
  });

  it("fills a starter prompt without invoking the model", async () => {
    mocks.activeSessions = [session()];
    mocks.getSession.mockResolvedValue(detail());
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /画像助手对话/ }));
    fireEvent.click(await screen.findByRole("button", { name: "整理我的后端开发经历" }));

    expect(screen.getByDisplayValue("整理我的后端开发经历")).toBeInTheDocument();
    expect(mocks.startExecution).not.toHaveBeenCalled();
  });
});
