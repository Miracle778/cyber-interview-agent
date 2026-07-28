import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BulkPublicationProgress } from "./BulkPublicationProgress";
import type { BulkPublication, QuestionCandidate } from "./reviewTypes";

const operation: BulkPublication = {
  id: "bulk-1", sessionId: "cs-1", executionId: "run-1", summaryVersion: 2, status: "running", retryCount: 0,
  items: [
    { id: "i1", operationId: "bulk-1", candidateId: "c1", idempotencyKey: "k1", status: "completed", errorCode: null, createdAt: "2026-07-26T00:00:00Z", updatedAt: "2026-07-26T00:00:01Z" },
    { id: "i2", operationId: "bulk-1", candidateId: "c2", idempotencyKey: "k2", status: "running", errorCode: null, createdAt: "2026-07-26T00:00:00Z", updatedAt: "2026-07-26T00:00:02Z" },
    { id: "i3", operationId: "bulk-1", candidateId: "c3", idempotencyKey: "k3", status: "pending", errorCode: null, createdAt: "2026-07-26T00:00:00Z", updatedAt: "2026-07-26T00:00:00Z" },
  ],
  createdAt: "2026-07-26T00:00:00Z", completedAt: null,
};
const candidate = (id: string, title: string) => ({ id, question: { title } } as QuestionCandidate);
const candidates = { c1: candidate("c1", "缓存雪崩"), c2: candidate("c2", "缓存击穿"), c3: candidate("c3", "缓存穿透") };

describe("BulkPublicationProgress", () => {
  afterEach(cleanup);

  it("shows durable per-item progress and lets the user stop the active run", () => {
    const onStop = vi.fn();
    render(<BulkPublicationProgress operation={operation} candidates={candidates} stopping={false} retrying={false} onStop={onStop} onRetry={vi.fn()} />);
    expect(screen.getByRole("region", { name: "一键发布进度" })).toHaveTextContent("已处理 1 / 3");
    expect(screen.getByText(/当前正在发布/)).toHaveTextContent("缓存击穿");
    fireEvent.click(screen.getByRole("button", { name: "停止发布" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("offers retry only for unfinished items after a partial failure", () => {
    const onRetry = vi.fn();
    const onOpenCandidate = vi.fn();
    render(<BulkPublicationProgress operation={{ ...operation, status: "partial_failure", completedAt: "2026-07-26T00:00:10Z", items: operation.items.map((item) => item.id === "i2" ? { ...item, status: "failed", errorCode: "publication_failed" } : item) }} candidates={candidates} stopping={false} retrying={false} onStop={vi.fn()} onRetry={onRetry} onOpenCandidate={onOpenCandidate} />);
    expect(screen.getByText("部分未完成")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "只看失败 1" }));
    expect(screen.queryByText("缓存雪崩")).toBeNull();
    expect(screen.getByText("缓存击穿")).toBeInTheDocument();
    expect(screen.getByText("写入题库时失败，题目仍保留，可以重试发布。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看失败题目：缓存击穿" }));
    expect(onOpenCandidate).toHaveBeenCalledWith("c2");
    fireEvent.click(screen.getByRole("button", { name: "重试未完成项" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
