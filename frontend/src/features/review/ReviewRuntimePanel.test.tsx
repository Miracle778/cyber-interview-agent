import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReviewRuntimePanel } from "./ReviewRuntimePanel";
import type { ReviewRound } from "./reviewTypes";

describe("ReviewRuntimePanel", () => {
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
});
