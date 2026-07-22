import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import type { CurationSession, QuestionCandidate } from "./reviewTypes";

const session = {
  id: "s1",
  stage: "waiting_for_command",
  summary: { items: [
    { ordinal: 1, candidateId: "c1", title: "MVCC", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" },
    { ordinal: 2, candidateId: "c2", title: "事务隔离", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" },
  ] },
  warnings: [],
  usage: { totalTokens: 20, callCount: 1 },
  contextUsage: { currentTokens: 32000, thresholdTokens: 89600 },
} as unknown as CurationSession;

function candidate(id: string, title: string, status: QuestionCandidate["status"], updatedAt = "2026-07-16T00:00:00Z"): QuestionCandidate {
  return {
    id,
    batchId: "b1",
    curationSessionId: "s1",
    sourceRefs: [],
    correctionNote: "",
    reviewNote: "",
    reviewNoteUpdatedAt: null,
    duplicateOfQuestionId: null,
    duplicateQuestion: null,
    status,
    draft: null,
    createdAt: "2026-07-16T00:00:00Z",
    updatedAt,
    question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: id, title, questionText: "问题", referenceAnswer: "答案", topics: ["database"], difficulty: "medium", keyPoints: [], followUps: [] },
  };
}

describe("CurationRuntimePanel candidate status", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-22T00:02:31+08:00"));
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });
  it("replaces misleading task progress with live candidate cards", () => {
    const { rerender } = render(<CurationRuntimePanel session={session} candidates={[candidate("c1", "MVCC", "review_pending"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z")]} />);
    const status = screen.getByRole("region", { name: "候选题实时状态" });
    expect(status).toHaveTextContent("事务隔离");
    expect(within(status).getAllByRole("button")[0]).toHaveTextContent("待确认");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(screen.queryByText("当前任务")).toBeNull();
    expect(screen.queryByText("整体进度")).toBeNull();

    rerender(<CurationRuntimePanel session={{ ...session, summary: { items: [...session.summary.items, { ordinal: 3, candidateId: "c3", title: "间隙锁", topics: ["database"], difficulty: "hard", sourceCount: 1, recommendation: "recommend_confirm" }] } }} candidates={[candidate("c1", "MVCC", "published", "2026-07-16T00:02:00Z"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z"), candidate("c3", "间隙锁", "review_pending", "2026-07-16T00:03:00Z")]} />);

    expect(status).toHaveTextContent("间隙锁");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("2");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
  });

  it("drills into shared markdown cards and delegates the same file actions", () => {
    const onFilter = vi.fn();
    const onOpen = vi.fn();
    const onPublish = vi.fn();
    const onSaveNote = vi.fn();
    const candidates = [candidate("c1", "MVCC", "review_pending"), candidate("c3", "历史锁题", "review_pending")];
    const { rerender } = render(<CurationRuntimePanel session={session} candidates={candidates} onStatusFilterChange={onFilter} />);

    fireEvent.click(screen.getByRole("button", { name: /待确认/ }));
    expect(onFilter).toHaveBeenCalledWith("review_pending");

    rerender(<CurationRuntimePanel session={session} candidates={candidates} statusFilter="review_pending" onStatusFilterChange={onFilter} onOpenCandidate={onOpen} onPublishCandidate={onPublish} onSaveNote={onSaveNote} />);
    const files = screen.getByRole("list", { name: "待确认文件" });
    expect(within(files).getAllByRole("article")).toHaveLength(2);
    expect(within(files).getByText("历史版本")).toBeInTheDocument();
    fireEvent.click(within(files).getAllByRole("button", { name: "查看" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "发布" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "备注" })[0]);
    fireEvent.change(screen.getByLabelText("修改备注"), { target: { value: "补充例子" } });
    fireEvent.click(screen.getByRole("button", { name: "保存备注" }));

    expect(onOpen).toHaveBeenCalledWith("c1");
    expect(onPublish).toHaveBeenCalledWith("c1");
    expect(onSaveNote).toHaveBeenCalledWith("c1", "补充例子");
    expect(screen.queryByText("运行详情")).toBeNull();
  });

  it("shows the current bounded generation phase and candidate limit", () => {
    render(<CurationRuntimePanel session={{
      ...session,
      stage: "generating",
      progress: { phase: "discovery", completed: 2, total: 5, generatedCandidateCount: 0, activeWorkers: 1 },
      warnings: [{ code: "candidate_limit_reached", limit: 200 }],
    }} />);

    const progress = screen.getByText("正在识别题目").closest("section");
    expect(progress).toHaveClass("curation-progress");
    expect(progress).not.toHaveClass("curation-retry");
    expect(screen.getByText("2 / 5")).toBeInTheDocument();
    expect(screen.getByText("已生成前 200 道候选题，请先审核当前结果")).toBeInTheDocument();
  });

  it("keeps the danger treatment for a failed execution", () => {
    render(<CurationRuntimePanel session={{
      ...session,
      stage: "failed",
      executionErrorCode: "provider_error",
      executionErrorMessage: "Agent 执行失败",
    }} />);

    const failure = screen.getByText("Agent 执行失败", { selector: "strong" }).closest("section");
    expect(failure).toHaveClass("curation-retry");
    expect(failure).not.toHaveClass("curation-progress");
    expect(failure).toHaveAttribute("role", "status");
    expect(failure).toHaveAttribute("aria-live", "polite");
  });

  it("shows durable seed quality as warnings and exposes one-seed recovery", () => {
    const onRetry = vi.fn();
    render(<CurationRuntimePanel session={{
      ...session,
      batchStatus: "review_pending",
      sources: [{ id: "s1", filename: "随手记.md", organizationState: "not_curated" }],
      seedProgress: { total: 5, completed: 1, degraded: 1, retrying: 1, skipped: 1, pending: 1 },
      qualitySummary: { source: 1, mixed: 1, model: 1, unknown: 0, needsReview: 2 },
      sourceWarnings: [{ sourceId: "s1", code: "low_signal" }],
      provisionalCandidates: [{ id: "seed-1", seedTaskId: "seed-1", title: "不完整问题", questionText: "Redis？", sourceRefs: ["s1"], status: "skipped", version: 3, answerBasis: "model", materialSupport: "minimal", needsReview: true, normalizationIssues: ["missing_answer"] }],
    }} onRetrySeed={onRetry} />);

    expect(screen.getByRole("status", { name: "整理进度" })).toHaveTextContent("1 / 5");
    expect(screen.getAllByText(/主要由 AI 生成/).length).toBeGreaterThan(0);
    expect(screen.getByText("材料支持较少")).toBeInTheDocument();
    expect(screen.getByText("随手记.md").closest("li")).toHaveTextContent("有效内容较少");
    const retry = screen.getByRole("button", { name: "重试这一题" });
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ seedTaskId: "seed-1", version: 3 }));
    expect(screen.queryByText("Agent 执行失败", { selector: "strong" })).toBeNull();
  });

  it("ticks from the server snapshot with a monotonic clock and ignores wall-clock skew", () => {
    let monotonicNow = 5_000;
    vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
    const running = {
      ...session,
      stage: "generating",
      batchStatus: "generating",
      executionId: "execution-1",
      executionStartedAt: "1999-01-01T00:00:00.000Z",
      progress: { phase: "enrichment", completed: 2, total: 5, generatedCandidateCount: 3, activeWorkers: 2 },
      timing: { currentElapsedMs: 10_000, cumulativeElapsedMs: 70_000 },
      controls: { canPause: true, canResume: false, canTerminate: true },
      provisionalCandidates: [],
    } as CurationSession;
    const { rerender } = render(<CurationRuntimePanel session={running} />);

    expect(screen.getByText("本次运行 10 秒")).toBeInTheDocument();
    expect(screen.getByText("累计运行 1 分 10 秒")).toBeInTheDocument();
    expect(screen.getByText("2 个工作单元运行中")).toBeInTheDocument();
    expect(screen.getByText("已生成 3 道候选")).toBeInTheDocument();
    const progress = screen.getByRole("status", { name: "整理进度" });
    expect(progress).toHaveAttribute("aria-live", "polite");
    expect(progress).toHaveTextContent("正在补全候选");
    expect(screen.getByText("本次运行 10 秒").closest("div")).toHaveAttribute("aria-live", "off");

    monotonicNow += 1_000;
    vi.setSystemTime(new Date("2036-01-01T00:00:00Z"));
    act(() => vi.advanceTimersByTime(1_000));

    expect(screen.getByText("本次运行 11 秒")).toBeInTheDocument();
    expect(screen.getByText("累计运行 1 分 11 秒")).toBeInTheDocument();

    rerender(<CurationRuntimePanel session={{
      ...running,
      timing: { currentElapsedMs: 8_000, cumulativeElapsedMs: 68_000 },
    }} />);
    expect(screen.getByText("本次运行 11 秒")).toBeInTheDocument();
    expect(screen.getByText("累计运行 1 分 11 秒")).toBeInTheDocument();

    monotonicNow += 1_000;
    vi.setSystemTime(new Date("2001-01-01T00:00:00Z"));
    act(() => vi.advanceTimersByTime(1_000));

    expect(screen.getByText("本次运行 12 秒")).toBeInTheDocument();
    expect(screen.getByText("累计运行 1 分 12 秒")).toBeInTheDocument();

    rerender(<CurationRuntimePanel session={{
      ...running,
      stage: "paused",
      batchStatus: "paused",
      timing: { currentElapsedMs: 9_000, cumulativeElapsedMs: 69_000 },
      controls: { canPause: false, canResume: true, canTerminate: true },
    }} />);
    monotonicNow += 5_000;
    act(() => vi.advanceTimersByTime(5_000));

    expect(screen.getByText("本次运行 9 秒")).toBeInTheDocument();
    expect(screen.getByText("累计运行 1 分 9 秒")).toBeInTheDocument();
  });

  it.each([
    ["paused", "paused", "已暂停", "curation-control-state--paused"],
    ["failed", "failed", "整理失败", "curation-control-state--failed"],
    ["interrupted", "interrupted", "服务中断", "curation-control-state--interrupted"],
    ["terminated", "terminated", "已终止", "curation-control-state--terminated"],
  ] as const)("freezes elapsed time and gives %s a distinct text and semantic class", (stage, batchStatus, label, className) => {
    render(<CurationRuntimePanel session={{
      ...session,
      stage,
      batchStatus,
      progress: { phase: "enrichment", completed: 2, total: 5, generatedCandidateCount: 3, activeWorkers: 0 },
      timing: { currentElapsedMs: 91_000, cumulativeElapsedMs: 151_000 },
      controls: { canPause: false, canResume: batchStatus !== "terminated", canTerminate: batchStatus !== "terminated" },
      provisionalCandidates: [],
    }} />);

    const state = screen.getByText(label).closest("section");
    expect(state).toHaveClass(className);
    expect(screen.getByText("本次运行 1 分 31 秒")).toBeInTheDocument();
    vi.advanceTimersByTime(3000);
    expect(screen.getByText("本次运行 1 分 31 秒")).toBeInTheDocument();
    if (batchStatus === "terminated") expect(screen.queryByRole("button", { name: "继续整理" })).toBeNull();
  });

  it("delegates pause, resume, and confirmed terminate as separate domain controls", () => {
    const onPause = vi.fn();
    const onResume = vi.fn();
    const onTerminate = vi.fn();
    const confirm = vi.spyOn(globalThis, "confirm").mockReturnValue(false);
    const { rerender } = render(<CurationRuntimePanel session={{
      ...session,
      stage: "generating",
      batchStatus: "generating",
      progress: { phase: "discovery", completed: 1, total: 4, generatedCandidateCount: 0, activeWorkers: 1 },
      timing: { currentElapsedMs: 1_000, cumulativeElapsedMs: 1_000 },
      controls: { canPause: true, canResume: false, canTerminate: true },
      provisionalCandidates: [],
    }} onPause={onPause} onResume={onResume} onTerminate={onTerminate} />);

    fireEvent.click(screen.getByRole("button", { name: "暂停整理" }));
    expect(onPause).toHaveBeenCalledTimes(1);
    const terminate = screen.getByRole("button", { name: "终止整理" });
    expect(terminate).toHaveClass("curation-control-actions__terminate");
    fireEvent.click(terminate);
    expect(confirm).toHaveBeenCalledWith("终止后将保留已有处理记录，但不能继续这个整理任务。确认终止？");
    expect(onTerminate).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(terminate);
    expect(onTerminate).toHaveBeenCalledTimes(1);

    rerender(<CurationRuntimePanel session={{
      ...session,
      stage: "paused",
      batchStatus: "paused",
      progress: { phase: "discovery", completed: 1, total: 4, generatedCandidateCount: 0, activeWorkers: 0 },
      timing: { currentElapsedMs: 1_000, cumulativeElapsedMs: 1_000 },
      controls: { canPause: false, canResume: true, canTerminate: true },
      provisionalCandidates: [],
    }} onPause={onPause} onResume={onResume} onTerminate={onTerminate} />);
    fireEvent.click(screen.getByRole("button", { name: "继续整理" }));
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it.each(["pause", "resume", "terminate"] as const)("disables every available control while %s is pending", (pending) => {
    const { rerender } = render(<CurationRuntimePanel session={{
      ...session,
      stage: "generating",
      batchStatus: "generating",
      progress: { phase: "discovery", completed: 1, total: 4, generatedCandidateCount: 0, activeWorkers: 1 },
      timing: { currentElapsedMs: 1_000, cumulativeElapsedMs: 1_000 },
      controls: { canPause: true, canResume: false, canTerminate: true },
      provisionalCandidates: [],
    }} controlPending={pending} />);

    expect(screen.getByRole("button", { name: "暂停整理" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "终止整理" })).toBeDisabled();

    rerender(<CurationRuntimePanel session={{
      ...session,
      stage: "paused",
      batchStatus: "paused",
      progress: { phase: "enrichment", completed: 1, total: 4, generatedCandidateCount: 1, activeWorkers: 0 },
      timing: { currentElapsedMs: 1_000, cumulativeElapsedMs: 1_000 },
      controls: { canPause: false, canResume: true, canTerminate: true },
      provisionalCandidates: [],
    }} controlPending={pending} />);

    expect(screen.getByRole("button", { name: "继续整理" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "终止整理" })).toBeDisabled();
  });

  it("renders provisional candidates as an explicitly read-only processing preview", () => {
    render(<CurationRuntimePanel session={{
      ...session,
      stage: "generating",
      batchStatus: "generating",
      progress: { phase: "enrichment", completed: 1, total: 3, generatedCandidateCount: 1, activeWorkers: 1 },
      timing: { currentElapsedMs: 5_000, cumulativeElapsedMs: 5_000 },
      controls: { canPause: true, canResume: false, canTerminate: true },
      provisionalCandidates: [{ id: "p1", title: "MVCC 可见性", questionText: "什么是 MVCC 的可见性规则？", sourceRefs: ["s1#1", "s1#2"] }],
    }} />);

    const preview = screen.getByRole("region", { name: "处理中候选预览" });
    expect(preview).toHaveTextContent("处理中预览");
    expect(preview).toHaveTextContent("MVCC 可见性");
    expect(preview).toHaveTextContent("2 条证据");
    expect(within(preview).queryByRole("button", { name: /编辑|确认|发布/ })).toBeNull();
  });
});
