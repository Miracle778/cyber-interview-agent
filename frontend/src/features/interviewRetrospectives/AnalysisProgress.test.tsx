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
