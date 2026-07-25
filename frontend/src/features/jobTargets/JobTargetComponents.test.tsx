import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { DeepDiveWorkspace } from "./DeepDiveWorkspace";
import { JobAnalysisStatus } from "./JobAnalysisStatus";
import { RequirementWorkbench } from "./RequirementWorkbench";
import { ProjectQuestionCandidates } from "./ProjectQuestionCandidates";
import { getTargetIdentity } from "./JobTargetWorkspace";
import { JobTargetList } from "./JobTargetList";
import type { DeepDiveResource, JobAnalysis, JobRequirement } from "./jobTargetTypes";

describe("job target workspace", () => {
  it("offers a compact target selector instead of forcing the desktop sidebar on mobile", () => {
    const onSelect = vi.fn();
    const targets = [
      { id: "one", workspaceId: "w", companyName: "示例公司", roleName: "后端工程师", seniority: "3 年", sourceUrl: null, lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "" },
      { id: "two", workspaceId: "w", companyName: null, roleName: "", seniority: "", sourceUrl: null, lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "" },
    ] as const;
    render(<JobTargetList targets={[...targets]} selectedId="one" onSelect={onSelect} onCreate={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("当前求职目标"), { target: { value: "two" } });
    expect(onSelect).toHaveBeenCalledWith("two");
    expect(screen.getByRole("option", { name: "岗位信息待补充" })).toBeInTheDocument();
  });

  it("keeps inferred requirements out of safe select-all", () => {
    const requirements = [
      { id: "direct", text: "负责高并发服务", sourceQuote: "负责高并发服务", inferred: false },
      { id: "inferred", text: "可能需要带团队", sourceQuote: "", inferred: true },
    ].map((item) => ({
      ...item, jobTargetId: "t", documentVersionId: "d", stableKey: item.id,
      requirementType: "responsibility", priority: "must_have",
      confirmationStatus: "pending", preparationStatus: "needs_deep_dive", version: 1,
    })) as JobRequirement[];
    const onDecide = vi.fn();
    render(<RequirementWorkbench requirements={requirements} onDecide={onDecide} />);
    expect(screen.getByText("推荐确认")).toBeVisible();
    expect(screen.getByText("人工确认")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认这条" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "一键确认推荐项" }));
    expect(onDecide).toHaveBeenCalledWith(["direct"], "confirmed");
    fireEvent.click(screen.getByRole("button", { name: "确认这条" }));
    expect(onDecide).toHaveBeenLastCalledWith(["direct"], "confirmed");
  });

  it("makes project-question evidence, editing, and batch confirmation usable", () => {
    const onBatchDecide = vi.fn();
    const onEdit = vi.fn();
    render(<ProjectQuestionCandidates projectTitle="订单系统" candidates={[{
      id: "candidate-1", dimension: "target_specific", status: "review_pending",
      question: {
        title: "订单系统 · 目标岗位追问",
        question: "如何用订单系统证明你胜任目标岗位？",
        rationale: "围绕目标岗位追问核对项目讲解。",
        requirements: [{ id: "r-1", text: "熟悉 Redis", priority: "must_have" }],
        projectFacts: ["负责核心服务设计和压测"],
        gaps: ["补充性能治理的取舍"],
      },
    }]} onDecide={vi.fn()} onBatchDecide={onBatchDecide} onEdit={onEdit} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "选择：如何用订单系统证明你胜任目标岗位？" }));
    fireEvent.click(screen.getByRole("button", { name: "确认选中并入库" }));
    expect(onBatchDecide).toHaveBeenCalledWith(["candidate-1"], "confirmed");
    fireEvent.click(screen.getByText("查看生成依据"));
    expect(screen.getByText("本次参考的岗位重点")).toBeVisible();
    expect(screen.getByText("熟悉 Redis")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("面试问题"), { target: { value: "请说明订单系统中的 Redis 取舍。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onEdit).toHaveBeenCalledWith("candidate-1", "订单系统 · 目标岗位追问", "请说明订单系统中的 Redis 取舍。");
    cleanup();
  });

  it("keeps team narration out of the confirmation queue and separates detail from bulk selection", () => {
    const requirements = [
      { id: "background", text: "团队服务于全站业务，产品包括服务注册中心", sourceQuote: "团队服务于全站业务，产品包括服务注册中心", inferred: false, requirementType: "responsibility", priority: "must_have", confirmationStatus: "confirmed" },
      { id: "redis", text: "熟悉 Redis", sourceQuote: "熟悉 Redis", inferred: false, requirementType: "skill", priority: "must_have", confirmationStatus: "pending" },
    ].map((item) => ({
      ...item, jobTargetId: "t", documentVersionId: "d", stableKey: item.id,
      preparationStatus: "needs_deep_dive", version: 1,
    })) as JobRequirement[];
    const { container } = render(<RequirementWorkbench requirements={requirements} onDecide={vi.fn()} />);

    expect(within(container).getByText("了解岗位背景")).toBeVisible();
    fireEvent.click(within(container).getByRole("button", { name: "技能要求 熟悉 Redis 推荐确认" }));
    expect(within(container).getByText(/已选 0 条/)).toBeVisible();
  });

  it("lets a confirmed requirement return to the pending queue for reconsideration", () => {
    const onDecide = vi.fn();
    const requirement = {
      id: "redis", jobTargetId: "t", documentVersionId: "d", stableKey: "redis",
      requirementType: "skill", priority: "must_have", text: "熟悉 Redis", sourceQuote: "熟悉 Redis",
      inferred: false, confirmationStatus: "confirmed", preparationStatus: "needs_deep_dive", version: 2,
    } satisfies JobRequirement;
    const { container } = render(<RequirementWorkbench requirements={[requirement]} onDecide={onDecide} />);

    fireEvent.click(within(container).getByRole("tab", { name: "已确认 1" }));
    fireEvent.click(within(container).getByRole("button", { name: "撤回确认" }));
    expect(onDecide).toHaveBeenCalledWith(["redis"], "pending");
  });

  it("enables selection and batch withdrawal in the confirmed queue", () => {
    const onDecide = vi.fn();
    const requirement = {
      id: "redis", jobTargetId: "t", documentVersionId: "d", stableKey: "redis",
      requirementType: "skill", priority: "must_have", text: "熟悉 Redis", sourceQuote: "熟悉 Redis",
      inferred: false, confirmationStatus: "confirmed", preparationStatus: "needs_deep_dive", version: 2,
    } satisfies JobRequirement;
    const { container } = render(<RequirementWorkbench requirements={[requirement]} onDecide={onDecide} />);

    fireEvent.click(within(container).getByRole("tab", { name: "已确认 1" }));
    fireEvent.click(within(container).getByRole("checkbox", { name: "选择：熟悉 Redis" }));
    fireEvent.click(within(container).getByRole("button", { name: "批量撤回确认" }));
    expect(onDecide).toHaveBeenCalledWith(["redis"], "pending");
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

  it("does not present a completed analysis as still identifying the role", () => {
    const target = {
      id: "t", workspaceId: "w", companyName: null, roleName: "", seniority: "", sourceUrl: null,
      lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "",
    } satisfies import("./jobTargetTypes").JobTarget;
    const identity = getTargetIdentity(target, {
      id: "a", jobTargetId: "t", status: "review_pending", stage: "waiting_for_review", version: 1,
      progress: { completed: 5, total: 5, activeWorkers: 0 }, timing: { currentElapsedMs: 0, cumulativeElapsedMs: 0 }, latestProgressAt: null,
      savedOutputs: { requirements: 4, projectMappings: 1 }, controls: { canPause: false, canResume: false, canTerminate: false },
    });
    expect(identity.title).toBe("岗位信息待补充");
    expect(identity.badge).toBe("待补充");
  });

  it("does not send while the IME is composing", () => {
    const onSend = vi.fn();
    const resource = {
      id: "d", jobTargetId: "t", projectClaimId: "p", sessionId: "s", status: "active",
      currentStage: "background", completedStageIds: [], waitingForInput: true, version: 1,
      messages: [], executions: [], artifacts: [], gaps: [], questionCandidates: [],
      runtime: { modelRole: "project_deep_dive", calls: 0, inputTokens: 0, outputTokens: 0, contextTokens: 0, contextThreshold: 0, estimated: true, compacted: false },
    } satisfies DeepDiveResource;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><DeepDiveWorkspace resource={resource} onSend={onSend} onStop={vi.fn()} onControl={vi.fn()} onRestart={vi.fn()} onChooseProject={vi.fn()} onRetry={vi.fn()} onResolve={vi.fn()} onDispatchGap={vi.fn()} onOpenProfile={vi.fn()} /></QueryClientProvider>);
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "你好" } });
    fireEvent.compositionStart(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("keeps recovery actions available after a paused answer", () => {
    const onRetry = vi.fn();
    const resource = {
      id: "paused", jobTargetId: "t", projectClaimId: "p", sessionId: "s", status: "paused",
      currentStage: "background", completedStageIds: [], waitingForInput: false, version: 1,
      messages: [{ id: "message-1", executionId: "execution-1", role: "user", content: "这是暂停前的回答", createdAt: "2026-07-25T08:00:00Z", resolutionStatus: "unresolved" }],
      executions: [{ id: "execution-1", inputMessageId: "message-1", retryOfExecutionId: null, status: "cancelled", errorMessage: null, createdAt: "2026-07-25T08:00:00Z", startedAt: "2026-07-25T08:00:01Z", finishedAt: "2026-07-25T08:00:02Z" }],
      artifacts: [], gaps: [], questionCandidates: [],
      runtime: { modelRole: "project_deep_dive", calls: 1, inputTokens: 10, outputTokens: 20, contextTokens: 30, contextThreshold: 100, estimated: false, compacted: false },
    } satisfies DeepDiveResource;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><DeepDiveWorkspace resource={resource} onSend={vi.fn()} onStop={vi.fn()} onControl={vi.fn()} onRestart={vi.fn()} onChooseProject={vi.fn()} onRetry={onRetry} onResolve={vi.fn()} onDispatchGap={vi.fn()} onOpenProfile={vi.fn()} /></QueryClientProvider>);

    expect(screen.getByText("上一次回答未完成")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "按原内容重试" }));
    expect(onRetry).toHaveBeenCalledWith("execution-1");
  });

  it("offers a fresh start, project switch, and actionable gaps after an ended session", () => {
    const onRestart = vi.fn();
    const onChooseProject = vi.fn();
    const onDispatchGap = vi.fn();
    const resource = {
      id: "ended", jobTargetId: "t", projectClaimId: "p", sessionId: "s", status: "terminated",
      currentStage: "role", completedStageIds: ["background"], waitingForInput: false, version: 2,
      messages: [], executions: [], artifacts: [], questionCandidates: [],
      gaps: [{ id: "gap-1", gap_kind: "knowledge", summary: "补充性能治理的取舍", status: "open" }],
      runtime: { modelRole: "project_deep_dive", calls: 1, inputTokens: 10, outputTokens: 20, contextTokens: 30, contextThreshold: 100, estimated: false, compacted: false },
    } satisfies DeepDiveResource;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><DeepDiveWorkspace resource={resource} onSend={vi.fn()} onStop={vi.fn()} onControl={vi.fn()} onRestart={onRestart} onChooseProject={onChooseProject} onRetry={vi.fn()} onResolve={vi.fn()} onDispatchGap={onDispatchGap} onOpenProfile={vi.fn()} /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "重新开始本项目" }));
    fireEvent.click(screen.getByRole("button", { name: "选择其他项目" }));
    fireEvent.click(screen.getByRole("button", { name: "补充性能治理的取舍 生成项目题" }));
    expect(onRestart).toHaveBeenCalledOnce();
    expect(onChooseProject).toHaveBeenCalledOnce();
    expect(onDispatchGap).toHaveBeenCalledWith(expect.objectContaining({ id: "gap-1" }));
  });
});
