import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DraftReview } from "./DraftReview";
import type { KnowledgeDraft } from "./draftTypes";


const draft: KnowledgeDraft = {
  id: "d1",
  workspaceId: "w1",
  sessionId: null,
  runId: null,
  agentType: null,
  domain: "review",
  documentType: "question",
  documentId: "q1",
  title: "缓存穿透",
  markdown: "# 缓存穿透\n",
  contentPath: "artifacts/review/drafts/d1.md",
  sourceRefs: [],
  relationRefs: [],
  status: "draft",
  version: 1,
  contentHash: "abc",
  createdAt: "now",
  updatedAt: "now",
  publication: null,
};


function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}


function mockFetchDrafts(impl: (url: string, init?: RequestInit) => unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const result = impl(url, init);
    if (result instanceof Response) return result;
    return Response.json(result);
  });
}


describe("DraftReview", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("loads and lists drafts, then shows the selected draft body", async () => {
    mockFetchDrafts((url) => {
      if (url.includes("/api/knowledge/drafts?")) return [draft];
      return [];
    });

    render(<DraftReview workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    expect(screen.getByLabelText("Markdown 正文")).toHaveValue("# 缓存穿透\n");
    expect(screen.getByText("版本 1")).toBeInTheDocument();
  });

  it("saves the draft with the current version", async () => {
    const fetchMock = mockFetchDrafts((url, init) => {
      if (url.includes("/api/knowledge/drafts?")) return [draft];
      if (url.endsWith("/api/knowledge/drafts/d1") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body.version).toBe(1);
        expect(body.title).toBe("缓存穿透（修订）");
        return { ...draft, title: "缓存穿透（修订）", version: 2, updatedAt: "later" };
      }
      return [];
    });

    render(<DraftReview workspaceId="w1" />, { wrapper });
    await screen.findByText("缓存穿透");
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "缓存穿透（修订）" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText("草稿已保存")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/api/knowledge/drafts/d1") && init?.method === "PATCH",
        ),
      ).toBe(true),
    );
  });

  it("reloads the draft after a version-conflict 409", async () => {
    const serverUpdated = {
      ...draft,
      title: "服务端已改",
      markdown: "# 服务端\n",
      version: 2,
      updatedAt: "later",
    };
    let draftsCalls = 0;
    mockFetchDrafts((url, init) => {
      if (url.includes("/api/knowledge/drafts?")) {
        draftsCalls += 1;
        return draftsCalls <= 1 ? [draft] : [serverUpdated];
      }
      if (url.endsWith("/api/knowledge/drafts/d1") && init?.method === "PATCH") {
        return Response.json(
          { code: "draft_version_changed", message: "草稿已更新" },
          { status: 409 },
        );
      }
      return [];
    });

    render(<DraftReview workspaceId="w1" />, { wrapper });
    await screen.findByText("缓存穿透");
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "本地编辑" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText(/草稿已被其他操作更新/)).toBeInTheDocument();
    expect(await screen.findByText("服务端已改")).toBeInTheDocument();
    expect(screen.getByLabelText("Markdown 正文")).toHaveValue("# 服务端\n");
  });

  it("requests publication and shows the waiting state", async () => {
    const pendingDraft = { ...draft, status: "review_pending" as const };
    let draftsCalls = 0;
    mockFetchDrafts((url, init) => {
      if (url.includes("/api/knowledge/drafts?")) {
        draftsCalls += 1;
        return draftsCalls <= 1 ? [draft] : [pendingDraft];
      }
      if (url.endsWith("/api/knowledge/drafts/d1/publish-request") && init?.method === "POST") {
        return { sessionId: "s1", runId: "r1", status: "waiting_for_approval" };
      }
      return [];
    });

    const onPublicationRequested = vi.fn();
    render(
      <DraftReview workspaceId="w1" onPublicationRequested={onPublicationRequested} />,
      { wrapper },
    );
    await screen.findByText("缓存穿透");
    fireEvent.click(screen.getByRole("button", { name: "请求发布" }));

    expect(await screen.findByText("已请求发布，等待人工确认")).toBeInTheDocument();
    expect(await screen.findByText("等待人工确认，批准后会发布到 Vault")).toBeInTheDocument();
    expect(onPublicationRequested).toHaveBeenCalledWith("r1");
  });

  it("shows the published path once a draft is published", async () => {
    const published = {
      ...draft,
      status: "published" as const,
      version: 2,
      publication: {
        state: "completed" as const,
        targetPath: "10_question_bank/q1.md",
        errorCode: null,
      },
    };
    mockFetchDrafts((url) => {
      if (url.includes("/api/knowledge/drafts?")) return [published];
      return [];
    });

    render(<DraftReview workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("已发布路径：knowledge-vault/10_question_bank/q1.md")).toBeInTheDocument();
    expect(screen.queryByText("已请求发布，等待人工确认")).toBeNull();
  });

  it("shows how to repair an index-stale publication", async () => {
    const stale = {
      ...draft,
      status: "published" as const,
      publication: {
        state: "index_stale" as const,
        targetPath: "10_question_bank/q1.md",
        errorCode: "publication_index_failed",
      },
    };
    mockFetchDrafts((url) => (url.includes("/api/knowledge/drafts?") ? [stale] : []));

    render(<DraftReview workspaceId="w1" />, { wrapper });

    expect(await screen.findByText(/索引尚未更新/)).toBeInTheDocument();
    expect(screen.getByText(/重新扫描 Vault/)).toBeInTheDocument();
  });

  it("maps an external-document conflict to actionable advice", async () => {
    mockFetchDrafts((url, init) => {
      if (url.includes("/api/knowledge/drafts?")) return [draft];
      if (url.endsWith("/api/knowledge/drafts/d1/publish-request") && init?.method === "POST") {
        return Response.json(
          { code: "external_document_changed", message: "Vault 文档已被外部修改" },
          { status: 409 },
        );
      }
      return [];
    });

    render(<DraftReview workspaceId="w1" />, { wrapper });
    await screen.findByText("缓存穿透");
    fireEvent.click(screen.getByRole("button", { name: "请求发布" }));

    expect(await screen.findByText(/Vault 文档已被外部修改/)).toBeInTheDocument();
  });
});
