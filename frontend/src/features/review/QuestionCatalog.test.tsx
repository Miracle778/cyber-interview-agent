import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionCatalog } from "./QuestionCatalog";

const workspace = { id: "w1", workspacePath: "/tmp/demo", vaultPath: "/tmp/demo/vault" };
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>; }

describe("QuestionCatalog", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("opens from curation history into a focused agent workspace", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([{ id: "s1", workspaceId: "w1", originalFilename: "mysql.md", storedPath: "sources/mysql.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null }]);
      if (url.includes("/api/review/question-candidates")) return Response.json([{ id: "c1", batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", draft: null, createdAt: "now", updatedAt: "now", question: { questionId: "q1", documentId: "d1", contentHash: "h1", title: "MVCC 可见性", questionText: "什么是 MVCC？", referenceAnswer: "版本可见性", topics: ["database"], difficulty: "medium", keyPoints: [], followUps: [] } }]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([{
        id: "cs1", workspaceId: "w1", title: "mysql.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "mysql.md", organizationState: "previously_curated" }], activeBatchId: "b1", executionId: "e1", executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [{ ordinal: 1, candidateId: "c1", title: "MVCC 可见性", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" }] }, summaryVersion: 1, warnings: [{ sourceId: "s1", state: "previously_curated" }], candidateCount: 1, pendingCount: 1, publishedCount: 0, messages: [{ id: "m0", executionId: "e1", role: "assistant", content: "正在生成候选题", messageKind: "stage", payload: {}, createdAt: "now" }, { id: "m1", executionId: "e1", role: "assistant", content: "整理完成，请确认推荐题。", messageKind: "curation_summary", payload: {}, createdAt: "now" }, { id: "m2", executionId: "e1", role: "user", content: "确认第 1 题", messageKind: "text", payload: {}, createdAt: "now" }], usage: { inputTokens: 12, outputTokens: 8, totalTokens: 20, callCount: 1, estimatedCount: 0 }, contextUsage: { currentTokens: 32000, thresholdTokens: 89600, estimated: true }, createdAt: "now", updatedAt: "now",
      }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    const session = await screen.findByRole("button", { name: /mysql\.md/ });
    expect(session).toHaveAttribute("title", "mysql.md");
    expect(screen.getByRole("tab", { name: "整理会话" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("region", { name: "历史整理会话" })).toBeInTheDocument();
    fireEvent.click(session);
    expect(screen.getByRole("log", { name: "整理对话" })).toHaveTextContent("整理完成，请确认推荐题");
    const summaryCard = screen.getByRole("region", { name: "已生成文件" });
    const laterMessage = screen.getByText("确认第 1 题");
    expect(summaryCard.compareDocumentPosition(laterMessage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const runtimePanel = screen.getByRole("complementary", { name: "整理运行状态" });
    expect(runtimePanel).toHaveTextContent("候选状态");
    expect(runtimePanel).toHaveTextContent("MVCC 可见性");
    expect(runtimePanel).not.toHaveTextContent("整体进度");
    expect(screen.getByText("提示").closest("details")).toHaveAttribute("open");
    const runtimeDetails = screen.getByText("运行详情").closest("details");
    expect(runtimeDetails).toHaveAttribute("open");
    expect(runtimeDetails).toHaveTextContent("0.02k");
    expect(runtimeDetails).toHaveTextContent("32k / 89.6k");
    expect(within(screen.getByRole("complementary", { name: "整理运行状态" })).queryByText("执行过程")).toBeNull();
    const processDetails = screen.getByText("Agent 处理完成").closest("details");
    expect(processDetails).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Agent 处理完成"));
    expect(processDetails).toHaveAttribute("open");
    expect(screen.getByLabelText("回复题匠")).toBeEnabled();
    expect(screen.getByRole("button", { name: "返回会话历史" })).toBeInTheDocument();
  });

  it("selects sources in a dialog and warns without blocking repeated curation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([
        { id: "s1", workspaceId: "w1", originalFilename: "mysql.md", storedPath: "sources/mysql.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null },
        { id: "s2", workspaceId: "w1", originalFilename: "redis.md", storedPath: "sources/redis.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null },
      ]);
      if (url.includes("/api/review/curation-sessions") && init?.method === "POST") return Response.json({ id: "cs2" }, { status: 202 });
      if (url.includes("/api/review/curation-sessions")) return Response.json([{ id: "cs1", workspaceId: "w1", title: "mysql.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "mysql.md", organizationState: "previously_curated" }], activeBatchId: null, executionId: null, executionStatus: null, stage: "completed", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 0, warnings: [], candidateCount: 0, pendingCount: 0, publishedCount: 0, messages: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "now", updatedAt: "now" }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    await screen.findByRole("button", { name: /mysql\.md/ });
    fireEvent.click(screen.getByRole("button", { name: "AI 整理" }));
    const dialog = screen.getByRole("dialog", { name: "选择整理资料" });
    expect(dialog).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/mysql\.md/));
    expect(screen.getByText("这份资料之前整理过，仍可再次整理并自动合并相似题。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始整理" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/curation-sessions",
      expect.objectContaining({ body: JSON.stringify({ workspaceId: "w1", sourceRefs: ["s1"] }) }),
    ));
  });

  it("keeps the question library as a separate secondary view", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([]);
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    await screen.findByRole("tab", { name: "整理会话" });
    fireEvent.click(screen.getByRole("button", { name: /已发布/ }));
    expect(await screen.findByRole("region", { name: "题目库浏览器" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "已入库 0" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("搜索候选题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回整理会话" })).toBeInTheDocument();
    expect(await screen.findByText("没有匹配的题目")).toBeInTheDocument();
  });

  it("uses the same global candidate facts for overview counts and library results", async () => {
    const candidate = (id: string, status: "published" | "review_pending") => ({ id, batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status, draft: null, createdAt: "now", updatedAt: "now", question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: `h-${id}`, title: `题目 ${id}`, questionText: "题目", referenceAnswer: "答案", topics: ["database"], difficulty: "medium", keyPoints: [], followUps: [] } });
    const allCandidates = [candidate("1", "published"), candidate("2", "published"), candidate("3", "review_pending")];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([{ id: "cs1", workspaceId: "w1", title: "mysql.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "mysql.md", organizationState: "previously_curated" }], activeBatchId: "b1", executionId: "e1", executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 1, warnings: [], candidateCount: 1, pendingCount: 0, publishedCount: 1, messages: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "now", updatedAt: "now" }]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) {
        const params = new URL(url, "http://localhost").searchParams;
        return Response.json(allCandidates.filter((item) => (!params.get("status") || item.status === params.get("status")) && (!params.get("topic") || item.question.topics.includes(params.get("topic")!))));
      }
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    const publishedSummary = await screen.findByRole("button", { name: /已发布/ });
    await waitFor(() => expect(publishedSummary).toHaveTextContent("2"));
    fireEvent.click(publishedSummary);
    expect(await screen.findByRole("button", { name: "已入库 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("2 道题目");
    const topic = screen.getByRole("button", { name: "database 2" });
    fireEvent.click(topic);
    await waitFor(() => expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("2 道题目"));
    expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("database主题");
  });

  it("opens publication approval in the current viewport instead of below the library", async () => {
    const pendingCandidate = { id: "c1", batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", draft: { id: "d1", title: "缓存雪崩", markdown: "# 缓存雪崩\n\n## 题目\n\n什么是缓存雪崩？\n\n## 参考答案\n\n大量缓存同时失效。", status: "review_pending", version: 1, contentHash: "h1", documentType: "question" }, createdAt: "now", updatedAt: "now", question: { questionId: "q1", documentId: "d1", contentHash: "h1", title: "缓存雪崩", questionText: "什么是缓存雪崩？", referenceAnswer: "大量缓存同时失效。", topics: ["Redis"], difficulty: "medium", keyPoints: [], followUps: [] } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([pendingCandidate]);
      if (url.endsWith("/api/knowledge/drafts/d1/publish-request") && init?.method === "POST") return Response.json({ sessionId: "publish-session", executionId: "publish-run", status: "waiting_for_approval" });
      if (url.includes("/api/agent/actions?")) return Response.json([{ id: "action-1", workspaceId: "w1", sessionId: "publish-session", executionId: "publish-run", actionType: "knowledge.publish", preview: { title: "缓存雪崩", markdown: pendingCandidate.draft.markdown }, editableFields: ["title", "markdown"], status: "pending", version: 1, createdAt: "now", resolvedAt: null }]);
      throw new Error(`unexpected ${url}`);
    });

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    await screen.findByRole("tab", { name: "题目库" });
    fireEvent.click(screen.getByRole("tab", { name: "题目库" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认入库" }));

    const dialog = await screen.findByRole("dialog", { name: "题目发布审批" });
    expect(dialog.parentElement).toHaveClass("dialog-backdrop");
    expect(within(dialog).getByRole("heading", { name: "发布审批" })).toBeInTheDocument();
    expect((await within(dialog).findAllByText("缓存雪崩")).length).toBeGreaterThan(0);
    expect(await within(dialog).findByRole("button", { name: "批准并入库" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "暂不发布" })).toBeInTheDocument();
    expect(within(dialog).queryByText("knowledge.publish")).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭发布审批" }));
    expect(screen.queryByRole("dialog", { name: "题目发布审批" })).toBeNull();
    const approvalEntry = screen.getByRole("button", { name: "打开待审批发布任务，共 1 项" });
    expect(approvalEntry).toBeInTheDocument();
    expect(approvalEntry.closest(".question-library__filters")).not.toBeNull();
    expect(screen.queryByRole("status", { name: "发布审批待处理" })).toBeNull();
    fireEvent.click(approvalEntry);
    expect(await screen.findByRole("dialog", { name: "题目发布审批" })).toBeInTheDocument();
  });

  it("shows public execution evidence and retries a failed curation session", async () => {
    const failedSession = {
      id: "cs-failed", workspaceId: "w1", title: "failed.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "failed.md", organizationState: "previously_curated" }], activeBatchId: "b1", executionId: "e1", executionStatus: "failed", executionStartedAt: "2026-07-15T10:00:00Z", executionFinishedAt: "2026-07-15T10:00:12Z", executionErrorCode: "provider_error", executionErrorMessage: "Agent 执行失败", contextCompacted: true, contextUsage: { currentTokens: 80000, thresholdTokens: 89600, estimated: true }, stage: "failed", progress: { completed: 1, total: 2 }, summary: { items: [] }, summaryVersion: 0, warnings: [], candidateCount: 0, pendingCount: 0, publishedCount: 0, messages: [{ id: "stage-1", executionId: "e1", role: "assistant", content: "正在读取所选资料", messageKind: "stage", payload: {}, createdAt: "2026-07-15T10:00:00Z" }], usage: { inputTokens: 12, outputTokens: 8, totalTokens: 20, callCount: 1, estimatedCount: 0 }, createdAt: "now", updatedAt: "now",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.endsWith("/retry") && init?.method === "POST") return Response.json({ ...failedSession, executionId: "e2", executionStatus: "running", stage: "generating" }, { status: 202 });
      if (url.includes("/api/review/curation-sessions")) return Response.json([failedSession]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /failed\.md/ }));
    const runtime = await screen.findByRole("complementary", { name: "整理运行状态" });
    await waitFor(() => expect(runtime).toHaveTextContent("Agent 执行失败"));
    expect(runtime).not.toHaveTextContent("耗时");
    expect(runtime).toHaveTextContent("0.02k");
    expect(runtime).toHaveTextContent("当前上下文 / 压缩阈值");
    const processDetails = screen.getByText("Agent 处理失败").closest("details");
    fireEvent.click(screen.getByText("Agent 处理失败"));
    expect(processDetails).toHaveTextContent("正在读取所选资料");
    fireEvent.click(within(runtime).getByRole("button", { name: "重试整理" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/curation-sessions/cs-failed/retry",
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("renders a command optimistically and reconciles the durable timeline", async () => {
    let finishCommand: (() => void) | undefined;
    let commandDone = false;
    const baseSession = { id: "cs1", workspaceId: "w1", title: "mysql.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "mysql.md", organizationState: "not_curated" }], activeBatchId: "b1", executionId: "e1", executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 1, warnings: [], candidateCount: 1, pendingCount: 1, publishedCount: 0, usage: { inputTokens: 12, outputTokens: 8, totalTokens: 20, callCount: 1, estimatedCount: 0 }, createdAt: "now", updatedAt: "now" };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.endsWith("/commands") && init?.method === "POST") {
        await new Promise<void>((resolve) => { finishCommand = () => { commandDone = true; resolve(); }; });
        return Response.json({ commandId: "command-1", executionId: "command-execution-1", status: "accepted" }, { status: 202 });
      }
      if (url.includes("/api/review/curation-sessions")) return Response.json([{ ...baseSession, messages: commandDone ? [{ id: "m-user", executionId: "command-execution-1", role: "user", content: "确认全部推荐题", messageKind: "text", payload: { resourceId: "command-1" }, createdAt: "now" }, { id: "m-receipt", executionId: "command-execution-1", role: "assistant", content: "已发布 1 道题。", messageKind: "command_receipt", payload: { resourceId: "command-1" }, createdAt: "now" }] : [] }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /mysql\.md/ }));
    const composer = await screen.findByLabelText("回复题匠");
    fireEvent.change(composer, { target: { value: "确认全部推荐题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByText("发送中…")).toBeInTheDocument();
    expect(screen.getByText("确认全部推荐题")).toBeInTheDocument();
    await waitFor(() => expect(finishCommand).toBeTypeOf("function"));
    finishCommand!();
    expect(await screen.findByText("已发布 1 道题。")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("发送中…")).toBeNull());
  });

  it("shows soft-deleted sessions and sources in the recycle bin", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/review/curation-sessions") && url.includes("deletedOnly=true")) return Response.json([{ id: "cs-trash", workspaceId: "w1", title: "deleted-session.md", sourceRefs: ["s-trash"], sources: [{ id: "s-trash", filename: "deleted-source.md", organizationState: "previously_curated" }], stage: "completed", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 0, warnings: [], candidateCount: 0, pendingCount: 0, publishedCount: 0, messages: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "now", updatedAt: "now", deletedAt: "now" }]);
      if (url.includes("/api/knowledge/sources") && url.includes("deletedOnly=true")) return Response.json([{ id: "s-trash", workspaceId: "w1", originalFilename: "deleted-source.md", storedPath: "sources/deleted.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "2026-07-15T10:00:00Z", draftId: null, deletedAt: "now" }]);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    await screen.findByRole("tab", { name: "整理会话" });
    fireEvent.click(screen.getByRole("button", { name: "回收站" }));
    const dialog = await screen.findByRole("dialog", { name: "回收站" });
    expect(await within(dialog).findByText("deleted-session.md")).toBeInTheDocument();
    expect(await within(dialog).findByText("deleted-source.md")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: "恢复" })).toHaveLength(2);
  });
});
