import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewResults } from "./ReviewResults";
import type { ReviewRound } from "./reviewTypes";

describe("ReviewResults", () => {
  it("rebuilds replay from durable attempts when legacy messages are absent", () => {
    const round = {
      id: "r1", workspaceId: "w1", sessionId: "s1", executionId: "e1",
      status: "completed", executionStatus: "completed", currentIndex: 1, questionCount: 1,
      attempts: [{ id: "a1", ordinal: 1, status: "completed", skipped: false, answer: "使用版本链", questionSnapshot: { title: "MVCC", questionText: "解释 MVCC" }, evaluation: { score: "partial", evidence: "覆盖版本链" } }],
      messages: [], reports: [],
    } as unknown as ReviewRound;
    render(<ReviewResults round={round} onDiscuss={vi.fn()} />);
    expect(screen.getByRole("button", { name: "已完成 1，点击筛选" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "会话回放" }));
    expect(screen.getByRole("log", { name: "复习会话回放" })).toHaveTextContent("由已保存的作答记录还原");
    expect(screen.getByRole("log", { name: "复习会话回放" })).toHaveTextContent("解释 MVCC");
    expect(screen.getByRole("log", { name: "复习会话回放" })).toHaveTextContent("使用版本链");
    expect(screen.getByRole("log", { name: "复习会话回放" }).querySelectorAll(".review-chat-message")).toHaveLength(3);
  });

  it("filters from the same attempt collection used by metric counts", () => {
    const discuss = vi.fn();
    const round = {
      id: "r1", executionId: "e1", status: "completed", executionStatus: "completed", currentIndex: 2, questionCount: 2, messages: [], reports: [], createdAt: "2026-07-19T01:00:00Z", updatedAt: "2026-07-19T01:10:00Z",
      attempts: [
        { id: "a1", ordinal: 1, status: "completed", skipped: false, answer: "A", questionSnapshot: { title: "题目 A", questionText: "A?" }, evaluation: { score: "good", evidence: "好" } },
        { id: "a2", ordinal: 2, status: "completed", skipped: true, answer: null, questionSnapshot: { title: "题目 B", questionText: "B?" }, evaluation: null },
      ],
    } as unknown as ReviewRound;
    render(<ReviewResults round={round} onDiscuss={discuss} />);
    fireEvent.click(screen.getByRole("button", { name: "掌握良好 1，点击筛选" }));
    expect(screen.getByText("已筛选：掌握良好").nextSibling).toHaveTextContent("1 道");
    expect(screen.getByText("1. 题目 A")).toBeInTheDocument();
    expect(screen.queryByText("2. 题目 B")).toBeNull();
    fireEvent.click(screen.getByText("1. 题目 A"));
    fireEvent.click(screen.getByRole("button", { name: "深入讨论" }));
    expect(discuss).toHaveBeenCalledWith(1);
  });
});
