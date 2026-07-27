import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewRuntimePanel } from "./ReviewRuntimePanel";
import type { ReviewRound } from "./reviewTypes";

describe("ReviewRuntimePanel", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the configured model name and every reported missing key point", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["providers"], [{ id: "provider-1", name: "火山", enabled: true, models: [{ id: "model-1", displayName: "glm", enabled: true }] }]);
    const missing = ["可达性分析", "从 GC Roots 沿引用链遍历", "GC Roots 的具体分类", "finalize 两次标记流程"];
    const round = {
      settings: { answer_model_id: "model-1", reasoning_effort: "medium" },
      status: "waiting_for_input",
      executionStatus: "waiting_for_input",
      attempts: [{ status: "completed", evaluation: { missing_key_points: missing, mastery_suggestion: "weak" }, masterySuggestion: "weak" }],
      usage: { totalTokens: 3100, callCount: 2 },
      contextUsage: { currentTokens: 0, thresholdTokens: 0 },
    } as ReviewRound;

    render(<QueryClientProvider client={client}><ReviewRuntimePanel round={round} /></QueryClientProvider>);

    expect(screen.getByText("火山 / glm")).toBeInTheDocument();
    const keyPoints = screen.getByText("待补充关键点").closest("details")!;
    const runtime = screen.getByText("运行详情").closest("details")!;
    expect(keyPoints).toHaveAttribute("open");
    expect(runtime).toHaveAttribute("open");
    expect(within(keyPoints).getAllByRole("listitem")).toHaveLength(4);
    expect(within(keyPoints).getByTitle("finalize 两次标记流程")).toBeInTheDocument();
    expect(within(runtime).getByText(/查看提示和答案直接读取本轮题库/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("运行详情"));
    expect(runtime).toHaveAttribute("open");
    expect(keyPoints).toHaveAttribute("open");
  });

  it("shows the current evaluation stage and live elapsed duration", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-19T10:00:03Z"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["providers"], []);
    const round = {
      settings: { answer_model_id: "model-1", reasoning_effort: "medium" },
      status: "running",
      executionStatus: "running",
      attempts: [{ id: "attempt-1", status: "evaluating", evaluationStartedAt: "2026-07-19T10:00:00Z", evaluationCompletedAt: null }],
      usage: { totalTokens: 0, callCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 0 },
    } as ReviewRound;

    render(<QueryClientProvider client={client}><ReviewRuntimePanel round={round} evaluationStage="checking_key_points" /></QueryClientProvider>);

    const runtime = screen.getByText("运行详情").closest("details")!;
    expect(within(runtime).getByText("对照必答方向")).toBeInTheDocument();
    expect(within(runtime).getByText("3 秒")).toBeInTheDocument();
  });
});
