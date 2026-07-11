import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { KnowledgePage } from "./KnowledgePage";

const workspace: WorkspaceConfig = {
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

describe("KnowledgePage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("requires workspace before upload or rescan", () => {
    render(
      <MemoryRouter>
        <KnowledgePage workspace={null} draftQuestion={null} onDraftQuestionReady={vi.fn()} onVaultRescanned={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("请先初始化工作区")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新扫描 Vault" })).toBeDisabled();
  });

  it("uploads source and displays the generated draft question", async () => {
    const onDraftQuestionReady = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(question), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={null}
        onDraftQuestionReady={onDraftQuestionReady}
        onVaultRescanned={vi.fn()}
      />,
    );

    const file = new File(["缓存穿透是什么？"], "cache.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("选择资料文件"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    await waitFor(() => expect(onDraftQuestionReady).toHaveBeenCalledWith(question));
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    expect(screen.getByText("缓存穿透是什么？")).toBeInTheDocument();
    expect(screen.getByText("关键点：缓存空值、布隆过滤器")).toBeInTheDocument();
  });

  it("rescans the vault and displays indexed count", async () => {
    const onVaultRescanned = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ indexed: 3 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(
      <KnowledgePage
        workspace={workspace}
        draftQuestion={question}
        onDraftQuestionReady={vi.fn()}
        onVaultRescanned={onVaultRescanned}
      />,
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
    );

    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    expect(screen.getByText("错误：请选择资料文件")).toBeInTheDocument();
    expect(screen.getByText("下一步：选择一份 txt、Markdown 或 PDF 资料")).toBeInTheDocument();
  });
});
