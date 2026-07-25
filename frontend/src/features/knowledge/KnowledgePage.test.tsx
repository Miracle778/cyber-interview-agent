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
function mockRoute(routes: Record<string, (init?: RequestInit, url?: string) => unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    for (const [prefix, handler] of Object.entries(routes)) {
      if (url.includes(prefix)) {
        const result = handler(init, url);
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
    expect(screen.getByRole("button", { name: "刷新资料" })).toBeDisabled();
  });

  it("uploads and displays a source without pretending a question was generated", async () => {
    const onDraftQuestionReady = vi.fn();
    let uploaded = false;
    const source = {
      id: "src1", workspaceId: "w1", originalFilename: "cache.txt",
      storedPath: "artifacts/review/sources/source_1.txt", contentType: "text/plain",
      sizeBytes: 15, createdAt: "2026-07-12T10:00:00Z", draftId: "d1",
    };
    const existingDraft = {
      id: "d-old",
      workspaceId: "w1", sessionId: null, executionId: null,
      agentType: null, domain: "review", documentType: "question",
      documentId: "q-old",
      title: "旧草稿",
      markdown: "# 旧草稿",
      contentPath: "artifacts/review/drafts/d-old.md", sourceRefs: [],
      relationRefs: [], status: "draft", version: 1, contentHash: "abc",
      createdAt: "now", updatedAt: "now",
    };
    const fetchMock = mockRoute({
      "/api/knowledge/sources": (init) => {
        if (init?.method === "POST") {
          uploaded = true;
          return { source: { ...source, draftId: null } };
        }
        return uploaded ? [source] : [];
      },
      "/api/knowledge/drafts?": () => [existingDraft],
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

    expect(await screen.findByRole("heading", { level: 1, name: "旧草稿" })).toBeInTheDocument();

    const file = new File(["缓存穿透是什么？"], "cache.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("选择资料文件"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "cache.txt" })).toBeInTheDocument());
    expect(onDraftQuestionReady).not.toHaveBeenCalled();
    const form = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes("/api/knowledge/sources") && init?.method === "POST",
    )?.[1]?.body as FormData;
    expect(form.get("workspaceId")).toBe("w1");
    expect(form.get("workspacePath")).toBeNull();
    expect(screen.getByText("已生成整理草稿")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "刷新资料" }));

    expect(await screen.findByText("已刷新 3 份资料")).toBeInTheDocument();
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

  it("keeps upload available and retries a failed source list", async () => {
    let sourceReads = 0;
    mockRoute({
      "/api/knowledge/sources?": () => {
        sourceReads += 1;
        return sourceReads === 1
          ? Response.json({ code: "api_error", message: "读取失败" }, { status: 500 })
          : [];
      },
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

    expect(await screen.findByText("资料读取失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "重试读取资料" }));
    expect(await screen.findByText("尚未上传资料")).toBeInTheDocument();
    expect(sourceReads).toBe(2);
  });

  it("groups persisted source documents and generated drafts", async () => {
    mockRoute({
      "/api/knowledge/sources?": () => [
        {
          id: "src1", workspaceId: "w1", originalFilename: "缓存资料.md",
          storedPath: "artifacts/review/sources/source_1.md", contentType: "text/markdown",
          sizeBytes: 1024, createdAt: "2026-07-12T10:00:00Z", draftId: "d1",
        },
      ],
      "/api/knowledge/drafts?": () => [
        {
          id: "d1", workspaceId: "w1", sessionId: null, executionId: null,
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

    expect(await screen.findByRole("heading", { name: "导入资料" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "整理结果" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /缓存资料\.md/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /缓存穿透/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "缓存穿透" })).toBeInTheDocument();

    const confirm = vi.spyOn(globalThis, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("Markdown 正文"), { target: { value: "# 未保存修改" } });
    fireEvent.click(screen.getByRole("button", { name: /缓存资料\.md/ }));
    expect(confirm).toHaveBeenCalledWith("放弃未保存的修改？");
    expect(screen.getByLabelText("Markdown 正文")).toHaveValue("# 未保存修改");

    fireEvent.click(screen.getByRole("button", { name: /缓存资料\.md/ }));
    expect(screen.getByRole("heading", { name: "缓存资料.md" })).toBeInTheDocument();
    expect(screen.getByText("已生成整理草稿")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看关联草稿" })).toBeInTheDocument();
    // knowledge page hides the diagnostic test button
    expect(screen.queryByRole("button", { name: "运行确认测试" })).toBeNull();
  });
});
