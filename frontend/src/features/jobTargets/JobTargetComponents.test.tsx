import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { DeepDiveWorkspace } from "./DeepDiveWorkspace";
import { JobAnalysisStatus } from "./JobAnalysisStatus";
import { RequirementWorkbench } from "./RequirementWorkbench";
import { ProjectQuestionCandidates } from "./ProjectQuestionCandidates";
import { getTargetIdentity, JobTargetWorkspace } from "./JobTargetWorkspace";
import { JobTargetList } from "./JobTargetList";
import { JobTargetOverview } from "./JobTargetOverview";
import { ProjectPriorityPanel } from "./ProjectPriorityPanel";
import type { DeepDiveResource, JobAnalysis, JobRequirement, JobTargetRetrospectiveSummary } from "./jobTargetTypes";

describe("job target workspace", () => {
  it("summarizes multi-round interview feedback without exposing report bodies", () => {
    const onOpenRetrospectives = vi.fn();
    const target = {
      id: "t", workspaceId: "w", companyName: "示例公司", roleName: "后端工程师", seniority: "3-5 年",
      sourceUrl: null, lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "",
    } satisfies import("./jobTargetTypes").JobTarget;
    const summary = {
      retrospectiveCount: 3,
      latest: { retrospectiveId: "r3", title: "三面复盘", roundLabel: "三面", interviewDate: "2026-08-01", outcome: "passed", lifecycleStatus: "active" },
      unresolvedActionCount: 2,
      gapCounts: { knowledge: 3, expression: 2 },
      timeline: [],
    } satisfies JobTargetRetrospectiveSummary;

    render(<JobTargetOverview target={target} retrospectiveSummary={summary} onEditJd={vi.fn()} onCompleteInfo={vi.fn()} onStartAnalysis={vi.fn()} onControl={vi.fn()} onNavigate={vi.fn()} onStartTargetReview={vi.fn()} onOpenRetrospectives={onOpenRetrospectives} />);

    const feedback = screen.getByRole("region", { name: "面试反馈" });
    expect(within(feedback).getByText("3")).toBeVisible();
    expect(within(feedback).getByText("最近一轮 · 通过")).toBeVisible();
    expect(within(feedback).getByText("2")).toBeVisible();
    expect(within(feedback).getByText(/知识 3 · 表达 2/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看全部复盘" }));
    expect(onOpenRetrospectives).toHaveBeenCalledOnce();
  });

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
    expect(screen.getByRole("button", { name: "岗位信息待补充 已保存岗位描述" })).toBeInTheDocument();
  });

  it("lets the desktop target list collapse into a compact rail", () => {
    const onToggleCollapsed = vi.fn();
    const target = {
      id: "one", workspaceId: "w", companyName: "示例公司", roleName: "后端工程师", seniority: "3 年",
      sourceUrl: null, lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "",
    } satisfies import("./jobTargetTypes").JobTarget;
    const { container, rerender } = render(<JobTargetList targets={[target]} selectedId="one" onSelect={vi.fn()} onCreate={vi.fn()} collapsed={false} onToggleCollapsed={onToggleCollapsed} />);

    fireEvent.click(within(container).getByRole("button", { name: "收起求职目标列表" }));
    expect(onToggleCollapsed).toHaveBeenCalledOnce();

    rerender(<JobTargetList targets={[target]} selectedId="one" onSelect={vi.fn()} onCreate={vi.fn()} collapsed onToggleCollapsed={onToggleCollapsed} />);
    expect(within(container).getByRole("button", { name: "展开求职目标列表" })).toBeVisible();
    expect(within(container).getByRole("button", { name: "后端工程师 示例公司 · 3 年" })).toBeVisible();
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

  it("offers project review only after a project question is confirmed", () => {
    const onStartReview = vi.fn();
    render(<ProjectQuestionCandidates projectTitle="订单系统" candidates={[{
      id: "candidate-confirmed", dimension: "architecture_solution", status: "confirmed",
      question: { title: "订单系统架构", question: "如何设计订单系统？" },
    }]} onStartReview={onStartReview} onDecide={vi.fn()} onBatchDecide={vi.fn()} onEdit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "开始项目专项复习" }));
    expect(onStartReview).toHaveBeenCalledOnce();
  });

  it("keeps team narration out of the confirmation queue and separates detail from bulk selection", () => {
    const requirements = [
      { id: "background", text: "团队服务于全站业务，产品包括服务注册中心", sourceQuote: "团队服务于全站业务，产品包括服务注册中心", inferred: false, requirementType: "responsibility", priority: "must_have", confirmationStatus: "confirmed" },
      { id: "metadata", text: "蚂蚁集团｜应用服务团队｜高级后端工程师（P6/P7）", sourceQuote: "蚂蚁集团｜应用服务团队｜高级后端工程师（P6/P7）", inferred: false, requirementType: "responsibility", priority: "must_have", confirmationStatus: "confirmed" },
      { id: "redis", text: "熟悉 Redis", sourceQuote: "熟悉 Redis", inferred: false, requirementType: "skill", priority: "must_have", confirmationStatus: "pending" },
    ].map((item) => ({
      ...item, jobTargetId: "t", documentVersionId: "d", stableKey: item.id,
      preparationStatus: "needs_deep_dive", version: 1,
    })) as JobRequirement[];
    const { container } = render(<RequirementWorkbench requirements={requirements} onDecide={vi.fn()} />);

    expect(within(container).getByText("了解岗位背景")).toBeVisible();
    expect(within(container).queryByRole("button", { name: /蚂蚁集团/ })).toBeNull();
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
    expect(screen.getByRole("list", { name: "岗位分析步骤" })).toBeVisible();
    expect(screen.getByText("读取岗位内容")).toBeVisible();
    expect(screen.getByText("分析项目相关性")).toBeVisible();
    expect(screen.getByText("18 秒")).toBeVisible();
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
    expect(identity.description).toContain("岗位名称和经验或职级范围");
  });

  it("turns the incomplete status into an explicit completion entry", () => {
    const onCompleteInfo = vi.fn();
    const target = {
      id: "t", workspaceId: "w", companyName: "示例公司", roleName: "", seniority: "3-5 年", sourceUrl: null,
      lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "",
    } satisfies import("./jobTargetTypes").JobTarget;
    const analysis = {
      id: "a", jobTargetId: "t", status: "review_pending", stage: "waiting_for_review", version: 1,
      progress: { completed: 5, total: 5, activeWorkers: 0 }, timing: { currentElapsedMs: 0, cumulativeElapsedMs: 0 }, latestProgressAt: null,
      savedOutputs: { requirements: 4, projectMappings: 1 }, controls: { canPause: false, canResume: false, canTerminate: false },
    } satisfies JobAnalysis;

    render(<JobTargetWorkspace target={target} analysis={analysis} tab="deep-dive" onTab={vi.fn()} onCompleteInfo={onCompleteInfo}><div>项目内容</div></JobTargetWorkspace>);

    expect(screen.getByText(/还缺岗位名称/)).toBeVisible();
    expect(screen.getByRole("link", { name: "面试复盘" })).toHaveAttribute("href", "/retrospectives?jobTargetId=t");
    fireEvent.click(screen.getByRole("button", { name: "待补充 补充岗位名称" }));
    expect(onCompleteInfo).toHaveBeenCalledOnce();
  });

  it("prioritizes incomplete target information and explains review readiness", () => {
    const onCompleteInfo = vi.fn();
    const onStartTargetReview = vi.fn();
    const target = {
      id: "t", workspaceId: "w", companyName: "示例公司", roleName: "", seniority: "", sourceUrl: null,
      lifecycleStatus: "active", currentDocumentVersionId: "d", version: 1, createdAt: "", updatedAt: "",
    } satisfies import("./jobTargetTypes").JobTarget;
    const readiness = {
      jobTargetId: "t", status: "requirements_pending", requirements: 5, coreProjectId: null, supplementaryProjectIds: [],
      pendingRequirements: 2, confirmedRequirements: 3, rejectedRequirements: 0, confirmedProjectQuestions: 0, profileVersion: 2,
    } satisfies import("./jobTargetTypes").TargetReadiness;

    render(<JobTargetOverview
      target={target}
      readiness={readiness}
      profileSummary={{ confirmedItems: 22, projectCount: 2 }}
      onEditJd={vi.fn()}
      onCompleteInfo={onCompleteInfo}
      onStartAnalysis={vi.fn()}
      onControl={vi.fn()}
      onNavigate={vi.fn()}
      onStartTargetReview={onStartTargetReview}
      onOpenRetrospectives={vi.fn()}
    />);

    expect(screen.getByRole("heading", { name: "先补全岗位信息" })).toBeVisible();
    expect(screen.getByText("3 条已确认")).toBeVisible();
    expect(screen.getByText("2 条待确认")).toBeVisible();
    expect(screen.getByText("22 条画像资料 · 2 个项目")).toBeVisible();
    expect(screen.getByRole("button", { name: "开始岗位专项复习" })).toBeDisabled();
    expect(screen.getByText("确认项目题后即可开始岗位专项复习")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "补全岗位信息" }));
    expect(onCompleteInfo).toHaveBeenCalledOnce();
    expect(onStartTargetReview).not.toHaveBeenCalled();
  });

  it("restores saved project priorities and makes save feedback visible", () => {
    const onSave = vi.fn();
    const { container } = render(<ProjectPriorityPanel
      projects={[{ id: "p1", title: "核心项目" }, { id: "p2", title: "补充项目" }]}
      initialCoreProjectId="p1"
      initialSupplementaryProjectIds={["p2"]}
      onSave={onSave}
      onStart={vi.fn()}
    />);

    expect(within(container).getByText("项目重点已保存")).toBeVisible();
    expect(within(container).getByRole("button", { name: "已保存" })).toBeDisabled();
    fireEvent.click(within(container).getByRole("checkbox", { name: "设为补充项目：补充项目" }));
    fireEvent.click(within(container).getByRole("button", { name: "保存项目重点" }));
    expect(onSave).toHaveBeenCalledWith("p1", []);
  });

  it("does not send while the IME is composing", () => {
    const onSend = vi.fn();
    const resource = {
      id: "d", jobTargetId: "t", projectClaimId: "p", sessionId: "s", status: "active",
      currentStage: "background", completedStageIds: [], waitingForInput: true, version: 1,
      messages: [], executions: [], artifacts: [], gaps: [], questionCandidates: [],
      runtime: { modelRole: "project_deep_dive", calls: 0, inputTokens: 0, outputTokens: 0, contextTokens: 885, contextThreshold: 89_600, estimated: true, compacted: false },
    } satisfies DeepDiveResource;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><DeepDiveWorkspace resource={resource} onSend={onSend} onStop={vi.fn()} onControl={vi.fn()} onRestart={vi.fn()} onChooseProject={vi.fn()} onRetry={vi.fn()} onResolve={vi.fn()} onDispatchGap={vi.fn()} onOpenProfile={vi.fn()} /></QueryClientProvider>);
    expect(screen.getByText("0.9k / 89.6k")).toBeInTheDocument();
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
