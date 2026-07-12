import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { KnowledgePage } from "./KnowledgePage";

const workspace: WorkspaceConfig = {
  id: "w1",
  workspacePath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
};

const question: ReviewQuestion = {
  id: "q1",
  title: "缓存穿透",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "缓存穿透是请求不存在的数据导致缓存无法命中。",
  topics: ["缓存"],
  difficulty: "medium",
  keyPoints: ["缓存空值", "布隆过滤器"],
  followUps: [],
  mastery: "unknown",
};

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  );
}

/** Routes fetch by URL so DraftReview/ActionCenter queries resolve to empty. */
function mockRoute(routes: Record<string, (init?: RequestInit) => unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    for (const [prefix, handler] of Object.entries(routes)) {
      if (url.includes(prefix)) {
        const result = handler(init);
        if (result instanceof Response) return result;
        return Response.json(result);
      }
    }
    return Response.json([], { status: 200 });
  });
}

describe("KnowledgePage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("requires workspace before upload or rescan", () => {
    render(<KnowledgePage workspace={null} draftQuestion={null} onDraftQuestionReady={vi.fn()} onVaultRescanned={vi.fn()} />, { wrapper });

    expect(screen.getByText("请先初始化工作区")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新扫描 Vault" })).toBeDisabled();
  });

  it("uploads source and displays the generated draft question", async () => {
    const onDraftQuestionReady = vi.fn();
    const fetchMock = mockRoute({
      "/api/knowledge/sources": () => ({
        draft: {
          id: "d1", workspaceId: "w1", sessionId: null, runId: null,
          agentType: null, domain: "review", documentType: "question",
          documentId: "q1", title: "缓存穿透", markdown: "# 缓存穿透",
          contentPath: "artifacts/review/drafts/d1.md", sourceRefs: [],
          relationRefs: [], status: "draft", version: 1, contentHash: "abc",
          createdAt: "now", updatedAt: "now",
        },
        question,
      }),
    });

    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={null}
        onDraftQuestionReady={onDraftQuestionReady}
        onVaultRescanned={vi.fn()}
      />,
      { wrapper },
    );

    const file = new File(["缓存穿透是什么？"], "cache.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("选择资料文件"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    await waitFor(() => expect(onDraftQuestionReady).toHaveBeenCalledWith(question));
    const form = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/knowledge/sources"))?.[1]?.body as FormData;
    expect(form.get("workspaceId")).toBe("w1");
    expect(form.get("workspacePath")).toBeNull();
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    expect(screen.getByText("缓存穿透是什么？")).toBeInTheDocument();
    expect(screen.getByText("关键点：缓存空值、布隆过滤器")).toBeInTheDocument();
  });

  it("rescans the vault and displays indexed count", async () => {
    const onVaultRescanned = vi.fn();
    mockRoute({ "/api/knowledge/rescan": () => ({ indexed: 3 }) });

    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={question}
        onDraftQuestionReady={vi.fn()}
        onVaultRescanned={onVaultRescanned}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "重新扫描 Vault" }));

    expect(await screen.findByText("索引文档数：3")).toBeInTheDocument();
    await waitFor(() => expect(onVaultRescanned).toHaveBeenCalledWith(3));
  });

  it("shows actionable advice when upload has no selected file", () => {
    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={null}
        onDraftQuestionReady={vi.fn()}
        onVaultRescanned={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    expect(screen.getByText("错误：请选择资料文件")).toBeInTheDocument();
    expect(screen.getByText("下一步：选择一份 txt、Markdown 或 PDF 资料")).toBeInTheDocument();
  });

  it("renders the draft review and publish action center when a workspace exists", async () => {
    mockRoute({
      "/api/knowledge/drafts?": () => [
        {
          id: "d1", workspaceId: "w1", sessionId: null, runId: null,
          agentType: null, domain: "review", documentType: "question",
          documentId: "q1", title: "缓存穿透", markdown: "# 缓存穿透",
          contentPath: "artifacts/review/drafts/d1.md", sourceRefs: [],
          relationRefs: [], status: "draft", version: 1, contentHash: "abc",
          createdAt: "now", updatedAt: "now",
        },
      ],
    });

    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={null}
        onDraftQuestionReady={vi.fn()}
        onVaultRescanned={vi.fn()}
      />,
      { wrapper },
    );

    expect(await screen.findByRole("heading", { name: "草稿审核" })).toBeInTheDocument();
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    // knowledge page hides the diagnostic test button
    expect(screen.queryByRole("button", { name: "运行确认测试" })).toBeNull();
  });
});
