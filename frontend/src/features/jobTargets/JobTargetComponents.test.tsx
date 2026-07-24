import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeepDiveWorkspace } from "./DeepDiveWorkspace";
import { JobAnalysisStatus } from "./JobAnalysisStatus";
import { RequirementWorkbench } from "./RequirementWorkbench";
import type { DeepDiveResource, JobAnalysis, JobRequirement } from "./jobTargetTypes";

describe("job target workspace", () => {
  it("keeps inferred requirements out of safe select-all", () => {
    const requirements = [
      { id: "direct", text: "负责高并发服务", sourceQuote: "负责高并发服务", inferred: false },
      { id: "inferred", text: "可能需要带团队", sourceQuote: "", inferred: true },
    ].map((item) => ({
      ...item, jobTargetId: "t", documentVersionId: "d", stableKey: item.id,
      requirementType: "responsibility", priority: "must_have",
      confirmationStatus: "pending", preparationStatus: "needs_deep_dive", version: 1,
    })) as JobRequirement[];
    render(<RequirementWorkbench requirements={requirements} onDecide={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "选择可安全确认项" }));
    expect(screen.getByRole("checkbox", { name: "负责高并发服务" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "可能需要带团队" })).not.toBeChecked();
    expect(screen.getByText("1 条推断建议需要单独核对")).toBeVisible();
  });

  it("shows persisted work facts instead of an indefinite spinner", () => {
    const analysis = {
      id: "a", jobTargetId: "t", status: "running", stage: "mapping_projects", version: 1,
      progress: { completed: 4, total: 7, activeWorkers: 1 },
      timing: { currentElapsedMs: 18_000, cumulativeElapsedMs: 42_000 },
      latestProgressAt: "2026-07-25T08:00:00Z",
      savedOutputs: { requirements: 12, projectMappings: 2 },
      controls: { canPause: true, canResume: false, canTerminate: true },
    } satisfies JobAnalysis;
    render(<JobAnalysisStatus analysis={analysis} />);
    expect(screen.getByText("正在分析项目相关性")).toBeVisible();
    expect(screen.getByText(/已完成 4 \/ 7/)).toBeVisible();
    expect(screen.getByText("12 条已保存")).toBeVisible();
  });

  it("does not send while the IME is composing", () => {
    const onSend = vi.fn();
    const resource = {
      id: "d", jobTargetId: "t", projectClaimId: "p", sessionId: "s", status: "active",
      currentStage: "background", completedStageIds: [], waitingForInput: true, version: 1,
      messages: [], executions: [], artifacts: [], gaps: [], questionCandidates: [],
      runtime: { modelRole: "project_deep_dive", calls: 0, inputTokens: 0, outputTokens: 0, contextTokens: 0, contextThreshold: 0, estimated: true, compacted: false },
    } satisfies DeepDiveResource;
    render(<DeepDiveWorkspace resource={resource} onSend={onSend} onControl={vi.fn()} onRetry={vi.fn()} onResolve={vi.fn()} />);
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "你好" } });
    fireEvent.compositionStart(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });
});
