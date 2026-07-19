import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewLanding } from "./ReviewLanding";
import type { ReviewRound } from "./reviewTypes";

const historyRound = {
  id: "r1", workspaceId: "w1", sessionId: "s1", executionId: "e1",
  settings: { topics: [], difficulties: ["medium"], mode: "random-mixed", question_count: 2, allow_follow_up: true, seed: 1, answer_model_id: "model-1", reasoning_effort: "medium" },
  status: "cancelled", executionStatus: "cancelled", currentIndex: 1, questionCount: 2,
  currentQuestion: null, currentInput: null, attempts: [{ id: "a1", ordinal: 1, status: "completed", skipped: false, answer: "回答", questionSnapshot: { title: "测试题目" } }, { id: "a2", ordinal: 2, status: "completed", skipped: true, answer: null, questionSnapshot: { title: "跳过题目" } }], messages: [], reports: [],
  usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, callCount: 0, estimatedCount: 0 }, createdAt: "2026-07-19T02:00:00Z", updatedAt: "2026-07-19T02:05:00Z", completedAt: null, archivedAt: null,
} as unknown as ReviewRound;

const callbacks = { onArchive: vi.fn(), onRestore: vi.fn() };

describe("ReviewLanding", () => {
  afterEach(cleanup);

  it("blocks creation and routes to curation when no questions are ready", () => {
    const create = vi.fn();
    const catalog = vi.fn();
    render(<ReviewLanding rounds={[]} questionCount={0} onCreate={create} onOpen={vi.fn()} onCatalog={catalog} {...callbacks} />);
    expect(screen.getByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建复习" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "题库尚未准备好" })).toHaveTextContent("当前没有已确认题目");
    fireEvent.click(screen.getByRole("button", { name: "去题库整理" }));
    expect(catalog).toHaveBeenCalledOnce();
    expect(create).not.toHaveBeenCalled();
  });

  it("allows a small round while suggesting more curation", () => {
    const create = vi.fn();
    render(<ReviewLanding rounds={[]} questionCount={4} onCreate={create} onOpen={vi.fn()} onCatalog={vi.fn()} {...callbacks} />);
    expect(screen.getByRole("status", { name: "题库题量偏少" })).toHaveTextContent("当前题库有 4 道题");
    fireEvent.click(screen.getByRole("button", { name: "创建复习" }));
    expect(create).toHaveBeenCalledOnce();
  });

  it("keeps the normal history view quiet when the catalog is ready", () => {
    render(<ReviewLanding rounds={[]} questionCount={10} onCreate={vi.fn()} onOpen={vi.fn()} onCatalog={vi.fn()} {...callbacks} />);
    expect(screen.queryByRole("status", { name: "题库尚未准备好" })).toBeNull();
    expect(screen.queryByRole("status", { name: "题库题量偏少" })).toBeNull();
  });

  it("uses readable history labels and counts actual answered questions", () => {
    render(<ReviewLanding rounds={[historyRound]} questionCount={10} onCreate={vi.fn()} onOpen={vi.fn()} onCatalog={vi.fn()} {...callbacks} />);
    expect(screen.getByLabelText("复习历史概览")).toHaveTextContent("已结束");
    expect(screen.getByLabelText("复习历史概览")).toHaveTextContent("已作答题目");
    expect(screen.getByRole("button", { name: /随机混合/ })).toHaveTextContent("中等难度");
    expect(screen.getByRole("button", { name: /随机混合/ })).toHaveTextContent("7月19日");
    expect(screen.getByRole("button", { name: /随机混合/ })).not.toHaveTextContent("model-1");
    expect(screen.getByRole("button", { name: /随机混合/ })).not.toHaveTextContent("需要恢复");
    fireEvent.click(screen.getByRole("button", { name: "已作答题目 1，点击查看条目" }));
    expect(screen.getByText("当前筛选：已作答题目").nextSibling).toHaveTextContent("1 条");
    expect(screen.getByRole("button", { name: /第 1 题/ })).toHaveTextContent("回答");
  });

  it("keeps archived rounds collapsed and restores them explicitly", () => {
    const restore = vi.fn();
    render(<ReviewLanding rounds={[{ ...historyRound, archivedAt: "2026-07-19T03:00:00Z" }]} questionCount={10} onCreate={vi.fn()} onOpen={vi.fn()} onCatalog={vi.fn()} onArchive={vi.fn()} onRestore={restore} />);
    const historyRegion = screen.getByLabelText("复习历史与归档");
    expect(historyRegion.querySelector(".review-landing__list")).toBeInTheDocument();
    expect(historyRegion.lastElementChild).toHaveClass("review-archive");
    expect(screen.getByRole("button", { name: "已结束 0，点击查看条目" })).toBeInTheDocument();
    expect(screen.getByText("已归档").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("已归档"));
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    expect(restore).toHaveBeenCalledWith(expect.objectContaining({ id: "r1" }));
  });
});
