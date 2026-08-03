import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnalysisProgress } from "./AnalysisProgress";

const run = {
  id: "run-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1",
  executionId: "execution-1", retryOfAnalysisRunId: null, status: "running",
  stage: "question_analysis", controlIntent: null, completedItems: 2, totalItems: 5,
  currentWorkKey: "question_analysis:q-3", cumulativeElapsedMs: 4_500,
  latestProgressAt: "2026-08-02 01:00:00", summary: null, version: 2,
  createdAt: "2026-08-02 00:59:55", updatedAt: "2026-08-02 01:00:00",
};

describe("AnalysisProgress", () => {
  it("shows real progress and exposes the matching run control", () => {
    const onStop = vi.fn();
    render(<AnalysisProgress run={run} busy={false} onStop={onStop} onResume={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText("已完成 2 / 5")).toBeVisible();
    expect(screen.getByText("正在分析第 3 个问题")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "停止分析" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("shows question-window extraction progress separately from question analysis", () => {
    const items = [
      { id: "e-1", questionUnitId: null, workKey: "question_extraction:1:20", status: "completed", attemptCount: 1, lastErrorCode: null, updatedAt: "now" },
      { id: "e-2", questionUnitId: null, workKey: "question_extraction:17:36", status: "running", attemptCount: 1, lastErrorCode: null, updatedAt: "now" },
      { id: "e-3", questionUnitId: null, workKey: "question_extraction:33:50", status: "pending", attemptCount: 0, lastErrorCode: null, updatedAt: "now" },
      { id: "r-1", questionUnitId: null, workKey: "question_reduce", status: "blocked", attemptCount: 0, lastErrorCode: null, updatedAt: "now" },
    ];
    render(<AnalysisProgress run={{ ...run, stage: "question_extraction", currentWorkKey: "question_extraction:17:36" }} items={items} busy={false} onStop={vi.fn()} onResume={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText("正在分段识别面试问题（1 / 3）")).toBeVisible();
  });

  it("collapses a completed run into one saved-result summary", () => {
    const view = render(<AnalysisProgress run={{ ...run, status: "completed", stage: "completed", completedItems: 5 }} busy={false} onStop={vi.fn()} onResume={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText("复盘分析已完成")).toBeVisible();
    expect(screen.getByText("5 个分析步骤已保存")).toBeVisible();
    expect(view.container.querySelector('[role="progressbar"]')).not.toBeInTheDocument();
  });

  it("offers resume after a stop and retry after a failure", () => {
    const onResume = vi.fn();
    const onRetry = vi.fn();
    const view = render(<AnalysisProgress run={{ ...run, status: "stopped", stage: "stopped" }} busy={false} onStop={vi.fn()} onResume={onResume} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "继续分析" }));
    expect(onResume).toHaveBeenCalledOnce();

    view.rerender(<AnalysisProgress run={{ ...run, status: "failed", stage: "failed" }} busy={false} onStop={vi.fn()} onResume={onResume} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "重试失败步骤" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
