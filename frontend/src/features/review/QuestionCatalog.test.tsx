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
    fireEvent.click(screen.getByRole("button", { name: "返回整理会话" }));
    expect(screen.getByRole("region", { name: "历史整理会话" })).toBeInTheDocument();
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
    expect(screen.getByRole("heading", { name: "题目库" })).toBeInTheDocument();
    expect(await screen.findByText("没有匹配的题目")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回整理会话" }));
    expect(screen.getByRole("region", { name: "历史整理会话" })).toBeInTheDocument();
  });

  it("opens an origin session directly even when it is absent from the session list", async () => {
    const candidate = { id: "c-old", batchId: "b-old", curationSessionId: "cs-old", sourceRefs: [], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "rejected", draft: null, createdAt: "now", updatedAt: "now", question: { questionId: "q-old", documentId: "d-old", contentHash: "h-old", title: "IAM 权限模型", questionText: "如何设计 IAM？", referenceAnswer: "使用最小权限。", topics: ["IAM"], difficulty: "hard", keyPoints: [], followUps: [] } };
    const originSession = { id: "cs-old", workspaceId: "w1", title: "iam.md", sourceRefs: [], sources: [], activeBatchId: "b-old", executionId: null, executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 1, warnings: [], candidateCount: 1, pendingCount: 0, publishedCount: 0, messages: [{ id: "m-old", executionId: null, role: "assistant", content: "IAM 题目整理完成", messageKind: "curation_summary", payload: {}, createdAt: "now" }], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false }, createdAt: "now", updatedAt: "now" };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/review/question-candidates/c-old/origin-session")) return Response.json({ status: "available", sessionId: "cs-old", session: originSession });
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([candidate]);
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      if (url.includes("/api/settings/providers")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("tab", { name: "题目库" }));
    fireEvent.click(await screen.findByRole("button", { name: "查看生成会话" }));

    expect(await screen.findByRole("log", { name: "整理对话" })).toHaveTextContent("IAM 题目整理完成");
    expect(screen.queryByText("正在查找原生成会话…")).toBeNull();
  });

  it("offers to restore an origin session from the recycle bin", async () => {
    const candidate = { id: "c-trash", batchId: "b-trash", curationSessionId: "cs-trash", sourceRefs: [], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "rejected", draft: null, createdAt: "now", updatedAt: "now", question: { questionId: "q-trash", documentId: "d-trash", contentHash: "h-trash", title: "回收站题目", questionText: "问题", referenceAnswer: "答案", topics: ["IAM"], difficulty: "hard", keyPoints: [], followUps: [] } };
    const restoredSession = { id: "cs-trash", workspaceId: "w1", title: "trash.md", sourceRefs: [], sources: [], activeBatchId: "b-trash", executionId: null, executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [] }, summaryVersion: 1, warnings: [], candidateCount: 1, pendingCount: 0, publishedCount: 0, messages: [], usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, contextUsage: { currentTokens: 0, thresholdTokens: 1000, estimated: false }, createdAt: "now", updatedAt: "now", deletedAt: null };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/review/question-candidates/c-trash/origin-session")) return Response.json({ status: "recycled", sessionId: "cs-trash", session: { ...restoredSession, deletedAt: "now" } });
      if (url.endsWith("/api/agent/sessions/cs-trash/restore") && init?.method === "POST") return Response.json({ id: "cs-trash" });
      if (url.endsWith("/api/review/curation-sessions/cs-trash")) return Response.json(restoredSession);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([candidate]);
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      if (url.includes("/api/settings/providers")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("tab", { name: "题目库" }));
    fireEvent.click(await screen.findByRole("button", { name: "查看生成会话" }));

    expect(await screen.findByText("原生成会话在回收站中，恢复后可以继续查看和修改。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "恢复并打开" }));
    expect(await screen.findByRole("region", { name: "整理会话工作台" })).toBeInTheDocument();
  });

  it("explains a missing curation projection instead of opening an empty workspace", async () => {
    const candidate = { id: "c-missing", batchId: "b-missing", curationSessionId: "cs-missing", sourceRefs: [], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "rejected", draft: null, createdAt: "now", updatedAt: "now", question: { questionId: "q-missing", documentId: "d-missing", contentHash: "h-missing", title: "IAM 历史题目", questionText: "问题", referenceAnswer: "答案", topics: ["IAM"], difficulty: "hard", keyPoints: [], followUps: [] } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/review/question-candidates/c-missing/origin-session")) return Response.json({ status: "projection_missing", sessionId: "cs-missing", session: null });
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([candidate]);
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("tab", { name: "题目库" }));
    fireEvent.click(await screen.findByRole("button", { name: "查看生成会话" }));

    expect(await screen.findByText("生成会话的展示记录不完整，暂时无法打开；题目和来源内容仍然保留。")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "整理会话工作台" })).toBeNull();
  });

  it("uses the same global candidate facts for overview counts and library results", async () => {
    const candidate = (id: string, status: "published" | "review_pending") => ({ id, batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status, draft: null, createdAt: "now", updatedAt: "now", question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: `h-${id}`, title: `题目 ${id}`, questionText: `题目 ${id}`, referenceAnswer: "答案", topics: ["database"], difficulty: "medium", keyPoints: [], followUps: [] } });
    const published = candidate("1", "published");
    const historicalVersion = { ...candidate("2", "published"), duplicateOfQuestionId: published.question.questionId };
    const allCandidates = [published, historicalVersion, candidate("3", "review_pending")];
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
    const totalSummary = await screen.findByRole("button", { name: /题目总数/ });
    await waitFor(() => expect(totalSummary).toHaveTextContent("2"));
    const publishedSummary = await screen.findByRole("button", { name: /已发布/ });
    await waitFor(() => expect(publishedSummary).toHaveTextContent("1"));
    fireEvent.click(totalSummary);
    await waitFor(() => expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("2 道逻辑题目"));
    fireEvent.click(screen.getByRole("button", { name: "返回整理会话" }));
    fireEvent.click(screen.getByRole("button", { name: /已发布/ }));
    expect(await screen.findByRole("button", { name: "已入库 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("1 道逻辑题目");
    const topic = screen.getByRole("button", { name: "database 1" });
    fireEvent.click(topic);
    await waitFor(() => expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("1 道逻辑题目"));
    expect(screen.getByRole("region", { name: "题目结果" })).toHaveTextContent("database主题");
  });

  it("promotes a candidate through the update-active-version flow", async () => {
    const active = { id: "c-active", batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, revisionOfQuestionId: null, isActiveVersion: true, status: "published", draft: { id: "d-active", title: "MVCC 原理", markdown: "# MVCC 原理", status: "published", version: 1, contentHash: "active-hash", documentType: "question" }, createdAt: "now", updatedAt: "2026-07-19T08:00:00Z", question: { questionId: "q-mvcc", documentId: "d-active", contentHash: "active-hash", title: "MVCC 原理", questionText: "MVCC 的实现原理是什么？", referenceAnswer: "旧答案", topics: ["MySQL"], difficulty: "medium", keyPoints: [], followUps: [] } };
    const candidate = { id: "c-next", batchId: "b2", curationSessionId: "cs2", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: "q-mvcc", duplicateQuestion: active.question, revisionOfQuestionId: null, isActiveVersion: false, status: "review_pending", draft: { id: "d-next", title: "MVCC 原理（新版）", markdown: "# MVCC 原理（新版）", status: "review_pending", version: 2, contentHash: "candidate-hash", documentType: "question" }, createdAt: "now", updatedAt: "2026-07-19T09:00:00Z", question: { questionId: "q-next", documentId: "d-next", contentHash: "candidate-hash", title: "MVCC 原理（新版）", questionText: "请说明 MVCC 的实现原理。", referenceAnswer: "新答案", topics: ["MySQL"], difficulty: "medium", keyPoints: [], followUps: [] } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/review/question-candidates/c-next/update-active-version") && init?.method === "POST") return Response.json({ ...candidate, status: "published", revisionOfQuestionId: "q-mvcc", isActiveVersion: true, question: { ...candidate.question, questionId: "q-mvcc" } });
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([active, candidate]);
      if (url.includes("/api/agent/actions?")) return Response.json([]);
      throw new Error(`unexpected ${url}`);
    });
    vi.spyOn(globalThis, "confirm").mockReturnValue(true);

    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("tab", { name: "题目库" }));
    fireEvent.click(await screen.findByRole("button", { name: /候选版本/ }));
    fireEvent.click(screen.getByRole("button", { name: "更新入库版" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/question-candidates/c-next/update-active-version",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"expectedActiveHash":"active-hash"'),
      }),
    ));
    expect(await screen.findByText(/旧版本已转为历史版本/)).toBeInTheDocument();
  });

  it("opens publication approval in the current viewport instead of below the library", async () => {
    const pendingCandidate = { id: "c1", batchId: "b1", curationSessionId: "cs1", sourceRefs: ["s1"], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", draft: { id: "d1", title: "缓存雪崩", markdown: "# 缓存雪崩\n\n## 题目\n\n什么是缓存雪崩？\n\n## 参考答案\n\n大量缓存同时失效。", status: "review_pending", version: 1, contentHash: "h1", documentType: "question" }, createdAt: "now", updatedAt: "now", question: { questionId: "q1", documentId: "d1", contentHash: "h1", title: "缓存雪崩", questionText: "什么是缓存雪崩？", referenceAnswer: "大量缓存同时失效。", topics: ["Redis"], difficulty: "medium", keyPoints: [], followUps: [] } };
    const existingAction = { id: "action-existing", workspaceId: "w1", sessionId: "existing-session", executionId: "existing-run", actionType: "knowledge.publish", preview: { title: "TCP 慢启动", markdown: "# TCP 慢启动" }, editableFields: ["title", "markdown"], status: "pending", version: 1, createdAt: "now", resolvedAt: null };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([pendingCandidate]);
      const publicationAction = { id: "action-1", workspaceId: "w1", sessionId: "publish-session", executionId: "publish-run", actionType: "knowledge.publish", preview: { title: "缓存雪崩", markdown: pendingCandidate.draft.markdown }, editableFields: ["title", "markdown"], status: "pending", version: 1, createdAt: "now", resolvedAt: null };
      if (url.endsWith("/api/knowledge/drafts/d1/publish-request") && init?.method === "POST") return Response.json({ sessionId: "publish-session", executionId: "publish-run", status: "waiting_for_approval", action: publicationAction, reused: false });
      if (url.includes("/api/agent/actions?")) return Response.json([existingAction]);
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
    expect(within(dialog).getByRole("button", { name: "退回修改" })).toBeInTheDocument();
    expect(within(dialog).queryByText("knowledge.publish")).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭发布审批" }));
    expect(screen.queryByRole("dialog", { name: "题目发布审批" })).toBeNull();
    const approvalEntry = screen.getByRole("button", { name: "打开待审批发布任务，共 2 项" });
    expect(approvalEntry).toBeInTheDocument();
    expect(approvalEntry.closest(".question-library__filters")).not.toBeNull();
    expect(screen.queryByRole("status", { name: "发布审批待处理" })).toBeNull();
    fireEvent.click(approvalEntry);
    const queueDialog = await screen.findByRole("dialog", { name: "题目发布审批" });
    expect(within(queueDialog).getByText("请选择要审批的题目")).toBeInTheDocument();
    expect(within(queueDialog).queryByRole("button", { name: "批准并入库" })).toBeNull();
    fireEvent.click(within(queueDialog).getByRole("button", { name: /TCP 慢启动/ }));
    expect(await within(queueDialog).findByRole("button", { name: "批准并入库" })).toBeInTheDocument();
    expect(within(queueDialog).getAllByText("TCP 慢启动").length).toBeGreaterThan(0);
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
