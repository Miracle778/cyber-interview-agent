import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionCatalog } from "./QuestionCatalog";

const workspace = { id: "w1", workspacePath: "/tmp/demo", vaultPath: "/tmp/demo/vault" };
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>; }

describe("QuestionCatalog", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("shows persisted candidates instead of an empty placeholder", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/knowledge/sources")) return Response.json([{ id: "s1", workspaceId: "w1", originalFilename: "mysql.md", storedPath: "sources/mysql.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null }]);
      if (url.includes("/api/review/question-batches")) return Response.json([]);
      if (url.includes("/api/review/question-candidates")) return Response.json([{ id: "c1", batchId: "b1", sourceRefs: ["s1"], correctionNote: "修正事务边界", duplicateOfQuestionId: null, duplicateQuestion: null, status: "published", createdAt: "now", updatedAt: "now", question: { questionId: "q1", documentId: "d1", contentHash: "h", title: "MVCC 可见性", questionText: "Read View 如何判断？", referenceAnswer: "比较上下界", topics: ["database"], difficulty: "medium", keyPoints: ["上下界"], followUps: [] }, draft: { id: "d1", title: "MVCC 可见性", markdown: "# MVCC 可见性", status: "published", version: 1, contentHash: "h", documentType: "question" } }]);
      throw new Error(`unexpected ${url}`);
    });
    render(<QuestionCatalog workspace={workspace} />, { wrapper });
    expect(await screen.findByRole("button", { name: /MVCC 可见性/ })).toBeInTheDocument();
    expect(screen.getByRole("article")).toHaveTextContent("MVCC 可见性");
    expect(screen.getByLabelText("Topic 筛选")).toBeInTheDocument();
    expect(screen.getByLabelText("来源筛选")).toBeInTheDocument();
    expect(screen.getByLabelText("状态筛选")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "来源证据" })).toHaveTextContent("mysql.md");
    expect(screen.queryByText("暂无候选题。选择资料后点击“AI 整理”。")).toBeNull();

    fireEvent.change(screen.getByLabelText("状态筛选"), { target: { value: "published" } });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("status=published"), expect.anything()));
  });
});
