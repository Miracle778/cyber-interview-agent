import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionCatalog } from "./QuestionCatalog";

const workspace = { id: "w1", workspacePath: "/tmp/demo", vaultPath: "/tmp/demo/vault" };
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>; }

describe("QuestionCatalog", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("opens in the durable three-pane curation session workbench", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([{ id: "s1", workspaceId: "w1", originalFilename: "mysql.md", storedPath: "sources/mysql.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null }]);
      if (url.includes("/api/review/curation-sessions")) return Response.json([{
        id: "cs1", workspaceId: "w1", title: "mysql.md", sourceRefs: ["s1"], sources: [{ id: "s1", filename: "mysql.md", organizationState: "previously_curated" }], activeBatchId: "b1", executionId: "e1", executionStatus: "completed", stage: "waiting_for_command", progress: { completed: 1, total: 1 }, summary: { items: [{ ordinal: 1, candidateId: "c1", title: "MVCC 可见性", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" }] }, summaryVersion: 1, warnings: [], candidateCount: 1, pendingCount: 1, publishedCount: 0, messages: [{ id: "m1", executionId: "e1", role: "assistant", content: "整理完成，请确认推荐题。", messageKind: "curation_summary", payload: {}, createdAt: "now" }], usage: { inputTokens: 12, outputTokens: 8, totalTokens: 20, callCount: 1, estimatedCount: 0 }, createdAt: "now", updatedAt: "now",
      }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    expect(await screen.findByRole("button", { name: /mysql\.md/ })).toHaveAttribute("title", "mysql.md");
    expect(screen.getByRole("tab", { name: "整理会话" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("complementary", { name: "整理会话列表" })).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "整理对话" })).toHaveTextContent("整理完成，请确认推荐题");
    expect(screen.getByRole("complementary", { name: "整理运行状态" })).toHaveTextContent("等待确认");
    expect(screen.getByLabelText("回复题匠")).toBeEnabled();
    const conversation = screen.getByRole("main");
    const sessionList = screen.getByRole("complementary", { name: "整理会话列表" });
    expect(within(conversation).getAllByText("mysql.md")).toHaveLength(1);
    expect(conversation.compareDocumentPosition(sessionList) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    await screen.findByRole("tab", { name: "整理会话" });
    fireEvent.click(screen.getByRole("tab", { name: "题目库" }));
    expect(await screen.findByLabelText("Topic 筛选")).toBeInTheDocument();
    expect(await screen.findByText("暂无候选题。选择资料后点击“AI 整理”。")).toBeInTheDocument();
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
        return Response.json({ id: "receipt-1", sessionId: "cs1", summaryVersion: 1, kind: "confirm", targetIds: [], status: "completed", result: {}, createdAt: "now", completedAt: "now" }, { status: 202 });
      }
      if (url.includes("/api/review/curation-sessions")) return Response.json([{ ...baseSession, messages: commandDone ? [{ id: "m-user", executionId: "e1", role: "user", content: "确认全部推荐题", messageKind: "text", payload: {}, createdAt: "now" }, { id: "m-receipt", executionId: "e1", role: "assistant", content: "已发布 1 道题。", messageKind: "command_receipt", payload: {}, createdAt: "now" }] : [] }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
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
});
