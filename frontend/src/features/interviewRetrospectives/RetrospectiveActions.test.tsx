import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveActions } from "./RetrospectiveActions";
import type { RetrospectiveActionItem } from "./retrospectiveTypes";

const actions: RetrospectiveActionItem[] = [
  { id: "action-1", retrospectiveId: "retro-1", analysisRunId: "run-1", questionUnitId: "q-1", gapId: "gap-1", actionKind: "knowledge", title: "补齐缓存异常场景", detail: "来自第一题", status: "pending", version: 1, completedAt: null, createdAt: "now", updatedAt: "now" },
  { id: "action-2", retrospectiveId: "retro-1", analysisRunId: "run-1", questionUnitId: "q-2", gapId: "gap-2", actionKind: "expression", title: "练习量化表达", detail: "来自第二题", status: "completed", version: 2, completedAt: "now", createdAt: "now", updatedAt: "now" },
];

afterEach(cleanup);

describe("RetrospectiveActions", () => {
  it("renders compact checklist actions and versioned decisions", () => {
    const onDecision = vi.fn();
    render(<MemoryRouter><RetrospectiveActions actions={actions} busy={false} draft={null} onDecision={onDecision} onCreateDraft={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("checkbox", { name: "完成：补齐缓存异常场景" }));
    expect(onDecision).toHaveBeenCalledWith(actions[0], "completed");
    fireEvent.click(screen.getByRole("checkbox", { name: "完成：练习量化表达" }));
    expect(onDecision).toHaveBeenCalledWith(actions[1], "pending");
    expect(screen.getByText("已完成 1 / 2")).toBeVisible();
  });

  it("offers selected safe sections without a raw transcript option", () => {
    const onCreateDraft = vi.fn();
    render(<MemoryRouter><RetrospectiveActions actions={actions} busy={false} draft={null} onDecision={vi.fn()} onCreateDraft={onCreateDraft} /></MemoryRouter>);
    expect(screen.queryByRole("checkbox", { name: /原始转写/ })).not.toBeInTheDocument();
    expect(screen.getByText(/文档草稿不会包含原始转写/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "生成复盘文档草稿" }));
    expect(onCreateDraft).toHaveBeenCalledWith(expect.arrayContaining(["basic_info", "confirmed_questions"]));
  });

  it("links a generated draft back to Knowledge", () => {
    render(<MemoryRouter><RetrospectiveActions actions={actions} busy={false} draft={{ id: "draft-1", documentType: "interview_retrospective", title: "一面复盘", markdown: "# 一面复盘", status: "draft", version: 1 }} onDecision={vi.fn()} onCreateDraft={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "前往知识库查看" })).toHaveAttribute("href", "/knowledge");
  });
});
