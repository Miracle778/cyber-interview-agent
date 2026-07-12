import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ReviewPage } from "./ReviewPage";
import type { ReviewQuestion } from "./reviewTypes";

class FakeEventSource {
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  constructor(public url: string) {}
  addEventListener() {}
  close() {}
}

const workspace: WorkspaceConfig = {
  id: "w1",
  workspacePath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
};

const question: ReviewQuestion = {
  id: "q1",
  title: "缓存穿透",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "请求不存在的数据导致缓存无法命中。",
  topics: ["缓存"],
  difficulty: "medium",
  keyPoints: ["缓存空值", "布隆过滤器"],
  followUps: [],
  mastery: "unknown",
};

const session = {
  id: "s1", workspaceId: "w1", graphId: "review.single", graphVersion: 1,
  title: "单题复习：缓存穿透", status: "active", createdAt: "now",
  updatedAt: "now", lastRunId: "r1",
};

describe("ReviewPage persistent runtime flow", () => {
  beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("requires a draft question before review", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json([], { status: 200 }),
    );
    render(<MemoryRouter><ReviewPage workspace={workspace} draftQuestion={null} /></MemoryRouter>);

    expect(screen.getByText("请先上传资料生成题库草稿")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送回答" })).toBeDisabled();
  });

  it("creates a review.single session and starts a run", async () => {
    const calls: string[] = [];
    let runBody: string | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);
      if (url.includes("/api/agent/sessions?")) return Response.json([]);
      if (url === "/api/agent/sessions" && method === "POST") return Response.json(session, { status: 201 });
      if (url === "/api/agent/sessions/s1/runs") {
        runBody = init?.body as string | undefined;
        return Response.json({ id: "r1", sessionId: "s1", status: "running", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null }, { status: 202 });
      }
      if (url === "/api/agent/sessions/s1") return Response.json({ ...session, messages: [{ id: "m1", runId: "r1", role: "user", content: "缓存空值", createdAt: "now" }], latestRun: { id: "r1", sessionId: "s1", status: "running", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null }, pendingAction: null });
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      throw new Error(`unexpected ${method} ${url}`);
    });
    render(<MemoryRouter><ReviewPage workspace={workspace} draftQuestion={question} /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("你的回答"), { target: { value: "缓存空值" } });
    fireEvent.click(screen.getByRole("button", { name: "发送回答" }));

    await waitFor(() => expect(calls).toContain("POST /api/agent/sessions"));
    expect(calls).toContain("POST /api/agent/sessions/s1/runs");
    expect(JSON.parse(runBody ?? "{}").input).toMatchObject({
      text: "缓存空值",
      user_answer: "缓存空值",
    });
    expect(await screen.findByText((_, node) => node?.tagName === "P" && node.textContent === "你：缓存空值")).toBeInTheDocument();
  });

  it("restores evaluation, draft and pending publication from persisted APIs", async () => {
    const olderSession = {
      ...session,
      id: "s-old",
      title: "旧复习会话",
      lastRunId: "r-old",
    };
    const action = {
      id: "a1", workspaceId: "w1", sessionId: "s1", runId: "r1",
      actionType: "knowledge.publish", preview: {
        draftId: "d1", question,
        evaluation: { score: "partial", missing_key_points: ["布隆过滤器"], evidence: "提到缓存空值" },
      }, editableFields: ["title", "markdown"], status: "pending", version: 1,
      createdAt: "now", resolvedAt: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/agent/sessions?")) return Response.json([session, olderSession]);
      if (url === "/api/agent/sessions/s1") return Response.json({ ...session, messages: [], latestRun: { id: "r1", sessionId: "s1", status: "waiting_for_approval", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null }, pendingAction: action });
      if (url.includes("/api/agent/actions?")) return Response.json([action]);
      if (url === "/api/knowledge/drafts/d1") return Response.json({ id: "d1", workspaceId: "w1", sessionId: "s1", runId: "r1", agentType: "review.single", domain: "review", documentType: "session_report", documentId: "doc1", title: "报告", markdown: "# 报告", contentPath: "draft.md", sourceRefs: ["q1"], relationRefs: [], status: "review_pending", version: 1, contentHash: "h1", createdAt: "now", updatedAt: "now", publication: null });
      throw new Error(`unexpected ${url}`);
    });

    render(<MemoryRouter><ReviewPage workspace={workspace} draftQuestion={null} /></MemoryRouter>);

    expect(await screen.findByText("评分：partial")).toBeInTheDocument();
    expect(screen.getByLabelText("历史会话")).toHaveValue("s1");
    expect(screen.getByText("草稿状态：review_pending")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准发布" })).toBeInTheDocument();
  });
});
