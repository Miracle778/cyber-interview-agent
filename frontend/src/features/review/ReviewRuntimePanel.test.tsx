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

  it("uses coverage to show partial and uncovered directions to improve", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["providers"], [{ id: "provider-1", name: "火山", enabled: true, models: [{ id: "model-1", displayName: "glm", enabled: true }] }]);
    const round = {
      settings: { answer_model_id: "model-1", reasoning_effort: "medium" },
      status: "waiting_for_input",
      executionStatus: "waiting_for_input",
      attempts: [{
        status: "completed",
        evaluation: { missing_key_points: ["未覆盖的 C"], mastery_suggestion: "weak" },
        masterySuggestion: "weak",
        coverage: [
          { point: "已覆盖的 A", status: "covered", evidence: ["回答证据"] },
          { point: "部分覆盖的 B", status: "partial", evidence: ["部分证据"] },
          { point: "未覆盖的 C", status: "uncovered", evidence: [] },
        ],
      }],
      usage: { totalTokens: 3100, callCount: 2 },
      contextUsage: { currentTokens: 0, thresholdTokens: 0 },
    } as unknown as ReviewRound;

    render(<QueryClientProvider client={client}><ReviewRuntimePanel round={round} /></QueryClientProvider>);

    expect(screen.getByText("火山 / glm")).toBeInTheDocument();
    const keyPoints = screen.getByText("待完善关键点").closest("details")!;
    const runtime = screen.getByText("运行详情").closest("details")!;
    expect(keyPoints).toHaveAttribute("open");
    expect(runtime).toHaveAttribute("open");
    expect(within(keyPoints).getAllByRole("listitem")).toHaveLength(2);
    expect(within(keyPoints).getByTitle("部分覆盖的 B")).toHaveTextContent("部分覆盖");
    expect(within(keyPoints).getByTitle("未覆盖的 C")).toHaveTextContent("未覆盖");
    expect(within(runtime).getByText(/查看提示和答案直接读取本轮题库/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("运行详情"));
    expect(runtime).toHaveAttribute("open");
    expect(keyPoints).toHaveAttribute("open");
  });

  it("prefers coverage when only a partial direction remains", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["providers"], []);
    const round = {
      settings: { answer_model_id: "model-1", reasoning_effort: "medium" },
      status: "waiting_for_input",
      executionStatus: "waiting_for_input",
      attempts: [{
        status: "completed",
        evaluation: { missing_key_points: [], mastery_suggestion: "partial" },
        coverage: [{ point: "部分覆盖的 B", status: "partial", evidence: [] }],
      }],
      usage: { totalTokens: 0, callCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 0 },
    } as unknown as ReviewRound;

    render(<QueryClientProvider client={client}><ReviewRuntimePanel round={round} /></QueryClientProvider>);

    const keyPoints = screen.getByText("待完善关键点").closest("details")!;
    expect(within(keyPoints).getAllByRole("listitem")).toHaveLength(1);
    expect(within(keyPoints).getByTitle("部分覆盖的 B")).toHaveTextContent("部分覆盖");
  });

  it("falls back to historical missing key points when coverage is absent", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["providers"], []);
    const round = {
      settings: { answer_model_id: "model-1", reasoning_effort: "medium" },
      status: "waiting_for_input",
      executionStatus: "waiting_for_input",
      attempts: [{
        status: "completed",
        evaluation: {
          missing_key_points: ["历史未覆盖项"],
          mastery_suggestion: "weak",
        },
      }],
      usage: { totalTokens: 0, callCount: 0 },
      contextUsage: { currentTokens: 0, thresholdTokens: 0 },
    } as ReviewRound;

    render(<QueryClientProvider client={client}><ReviewRuntimePanel round={round} /></QueryClientProvider>);

    const keyPoints = screen.getByText("待完善关键点").closest("details")!;
    expect(within(keyPoints).getAllByRole("listitem")).toHaveLength(1);
    expect(within(keyPoints).getByTitle("历史未覆盖项")).toHaveTextContent("未覆盖");
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
