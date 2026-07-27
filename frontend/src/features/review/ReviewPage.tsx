import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, FileCheck2, MoreHorizontal, PanelLeftOpen, PanelRightClose, PanelRightOpen, RotateCcw, StopCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { toActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import { listActions } from "../agent/hitlApi";
import type { PendingAction } from "../agent/hitlTypes";
import { MarkdownView } from "../knowledge/MarkdownView";
import { useAgentEvents } from "../agent/useAgentEvents";
import type { AgentEvent } from "../agent/agentTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { archiveReviewRound, cancelReviewRound, createReviewDiscussion, createReviewRound, getReviewRound, interruptReviewEvaluation, listActiveQuestions, listReviewRounds, restoreReviewRound, retryReviewEvaluation, retryReviewRound, skipReviewQuestion, submitReviewAnswer } from "./reviewApi";
import { QuestionCatalog } from "./QuestionCatalog";
import { ReviewAttemptPreview } from "./ReviewAttemptPreview";
import { ReviewConversation, type ReviewEvaluationStage } from "./ReviewConversation";
import { ReviewDiscussion } from "./ReviewDiscussion";
import { ReviewLanding } from "./ReviewLanding";
import { ReviewResults } from "./ReviewResults";
import { ReviewRuntimePanel } from "./ReviewRuntimePanel";
import { ReviewSetup } from "./ReviewSetup";
import { ReviewShell, type ReviewSection } from "./ReviewShell";
import type { ReviewQuestion, ReviewRound, ReviewTimelineMessage } from "./reviewTypes";

interface ReviewPageProps { workspace: WorkspaceConfig | null; draftQuestion?: ReviewQuestion | null; }

function commandId(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

function currentEvaluationStage(events: AgentEvent[], attemptId: string | null): ReviewEvaluationStage {
  if (!attemptId) return "preparing";
  let stage: ReviewEvaluationStage = "preparing";
  for (const event of events) {
    const payloadAttemptId = "attemptId" in event.payload && typeof event.payload.attemptId === "string"
      ? event.payload.attemptId
      : null;
    if (payloadAttemptId !== attemptId) continue;
    if (event.type === "review.evaluation.checking_key_points") stage = "checking_key_points";
    if (event.type === "review.evaluation.deciding_follow_up") stage = "deciding_follow_up";
  }
  return stage;
}

function ReviewQuestionStepper({ round, viewedOrdinal, onSelect }: { round: ReviewRound; viewedOrdinal: number | null; onSelect: (ordinal: number) => void }) {
  const [expandedRange, setExpandedRange] = useState<{ start: number; end: number } | null>(null);
  const current = Math.min(round.currentIndex, Math.max(0, round.questionCount - 1));
  const all = Array.from({ length: round.questionCount }, (_, index) => index);
  const indexes = round.questionCount <= 5 ? all : [...new Set([0, Math.max(0, current - 1), current, Math.min(round.questionCount - 1, current + 1), round.questionCount - 1])].sort((left, right) => left - right);
  const entries: Array<{ kind: "question"; index: number } | { kind: "gap"; start: number; end: number }> = [];
  indexes.forEach((index, position) => {
    const previous = indexes[position - 1];
    if (position > 0 && previous !== index - 1) entries.push({ kind: "gap", start: previous + 1, end: index - 1 });
    entries.push({ kind: "question", index });
  });

  useEffect(() => {
    setExpandedRange(null);
  }, [round.id, round.currentIndex]);

  const selectQuestion = (ordinal: number) => {
    setExpandedRange(null);
    onSelect(ordinal);
  };

  return <nav className="review-question-stepper" aria-label="本轮题目进度">
    <ol>{entries.map((entry) => {
      if (entry.kind === "gap") {
        const startOrdinal = entry.start + 1;
        const endOrdinal = entry.end + 1;
        const expanded = expandedRange?.start === entry.start && expandedRange.end === entry.end;
        return <li key={`gap-${entry.start}-${entry.end}`} className="review-question-stepper__gap">
          <button
            type="button"
            className="review-question-stepper__ellipsis"
            aria-label={`查看第 ${startOrdinal} 至 ${endOrdinal} 题`}
            aria-expanded={expanded}
            onClick={() => setExpandedRange(expanded ? null : { start: entry.start, end: entry.end })}
          >…</button>
        </li>;
      }
      const index = entry.index;
      const ordinal = index + 1;
      const attempt = round.attempts.find((item) => item.ordinal === ordinal);
      const isCurrent = index === current;
      const selected = viewedOrdinal === ordinal || (viewedOrdinal === null && isCurrent);
      const title = isCurrent ? round.currentQuestion?.title : attempt?.questionSnapshot.title;
      const completed = Boolean(attempt) || round.status === "completed";
      const status = attempt?.skipped ? "已跳过" : attempt ? "已完成" : "待开始";
      const content = <>
        <span className="review-question-stepper__number">{ordinal}</span>
        <span><small>{viewedOrdinal === ordinal ? `正在回看第 ${ordinal} 题` : isCurrent ? `第 ${ordinal} / ${round.questionCount} 题` : `第 ${ordinal} 题 · ${status}`}</small><strong>{title ?? "待开始"}</strong></span>
      </>;
      return <li key={index} aria-current={selected ? "step" : undefined} data-active-question={isCurrent || undefined} data-completed={completed || undefined} data-skipped={attempt?.skipped || undefined}>
        {attempt || isCurrent
          ? <button type="button" aria-label={isCurrent ? `返回当前第 ${ordinal} 题：${title}` : `回看第 ${ordinal} 题：${title}，${status}`} onClick={() => selectQuestion(ordinal)}>{content}</button>
          : <span className="review-question-stepper__item">{content}</span>}
      </li>;
    })}</ol>
    {expandedRange ? <section className="review-question-stepper__picker" aria-label={`第 ${expandedRange.start + 1} 至 ${expandedRange.end + 1} 题`}>
      <header>
        <strong>选择要回看的题目</strong>
        <button type="button" onClick={() => setExpandedRange(null)}>收起</button>
      </header>
      <div>{Array.from({ length: expandedRange.end - expandedRange.start + 1 }, (_, offset) => expandedRange.start + offset).map((index) => {
        const ordinal = index + 1;
        const attempt = round.attempts.find((item) => item.ordinal === ordinal);
        const status = attempt?.skipped ? "已跳过" : attempt ? "已完成" : "待开始";
        const title = attempt?.questionSnapshot.title ?? "尚未开始";
        return <button
          type="button"
          key={ordinal}
          disabled={!attempt}
          aria-label={attempt ? `回看第 ${ordinal} 题：${title}，${status}` : `第 ${ordinal} 题，待开始`}
          onClick={() => selectQuestion(ordinal)}
        >
          <span>{ordinal}</span>
          <span><strong>{title}</strong><small>{status}</small></span>
        </button>;
      })}</div>
    </section> : null}
    <div className="review-question-stepper__track" aria-hidden="true"><span style={{ width: `${Math.max(4, ((current + 1) / round.questionCount) * 100)}%` }} /></div>
  </nav>;
}

function ReviewTerminalState({ round, recovering, onRecover }: { round: ReviewRound; recovering: boolean; onRecover: () => void }) {
  const recoverable = round.executionStatus === "failed" && !["completed", "cancelled", "failed"].includes(round.status);
  return <section className={`review-terminal-state${recoverable ? " is-recoverable" : ""}`} role="status" aria-label={recoverable ? "复习轮次需要恢复" : "复习轮次已结束"}>
    <span aria-hidden="true">{recoverable ? <RotateCcw size={22} /> : <StopCircle size={22} />}</span>
    <div><h2>{recoverable ? "本轮执行中断" : "本轮已结束"}</h2><p>{recoverable ? "回答和评价记录都已保留，可以从中断位置继续。" : round.attempts.length ? `已保留 ${round.attempts.length} 道题的回答与评价记录。` : "本轮尚未产生回答记录。"}</p></div>
    {recoverable ? <Button loading={recovering} onClick={onRecover}><RotateCcw size={16} />恢复本轮</Button> : null}
  </section>;
}

function ReviewReportViewer({
  report,
  queue,
  nextReportId,
  onSelect,
  onCollapse,
}: {
  report: ReviewRound["reports"][number];
  queue: ReactNode;
  nextReportId: string | null;
  onSelect: (reportId: string) => void;
  onCollapse: () => void;
}) {
  const confirmed = Boolean(report.publication);
  return (
    <Card
      title="报告详情"
      icon={<FileCheck2 size={18} />}
      className="review-report-viewer"
      bodyClassName="review-report-viewer__body"
      actions={(
        <button type="button" className="review-pane-collapse" aria-label="收起报告详情，展开复习结果" title="收起报告详情" onClick={onCollapse}>
          <PanelRightClose size={18} />
        </button>
      )}
    >
      {queue}
      <div className="review-report-viewer__content">
        <header>
          <div>
            <span>{report.reportKind === "mastery_report" ? "掌握度更新" : "复习报告"}</span>
            <h2>{report.title}</h2>
          </div>
          <strong data-tone={confirmed ? "success" : "neutral"}>{confirmed ? "已确认" : "已退回"}</strong>
        </header>
        <MarkdownView markdown={report.markdown} />
      </div>
      {nextReportId ? (
        <footer className="review-report-viewer__footer">
          <span>这份报告已处理，下一份正在等待确认。</span>
          <Button size="sm" onClick={() => onSelect(nextReportId)}>继续确认下一份</Button>
        </footer>
      ) : null}
    </Card>
  );
}

export function ReviewPage({ workspace }: ReviewPageProps) {
  const client = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const [section, setSection] = useState<ReviewSection>("practice");
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [optimisticMessage, setOptimisticMessage] = useState<ReviewTimelineMessage | null>(null);
  const [discussionTarget, setDiscussionTarget] = useState<{ sessionId: string; ordinal: number } | null>(null);
  const [viewedOrdinal, setViewedOrdinal] = useState<number | null>(null);
  const [resultPaneMode, setResultPaneMode] = useState<"split" | "results" | "approval">("split");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const focusedWorkspaceRef = useRef<HTMLElement | null>(null);
  const reportApprovalRef = useRef<HTMLElement | null>(null);
  const rounds = useQuery({ queryKey: ["review-rounds", workspaceId], queryFn: () => listReviewRounds(workspaceId), enabled: Boolean(workspace) });
  const questions = useQuery({ queryKey: ["active-review-questions", workspaceId], queryFn: () => listActiveQuestions(workspaceId), enabled: Boolean(workspace) });
  const round = useQuery({ queryKey: ["review-round", selectedRoundId], queryFn: () => getReviewRound(selectedRoundId!), enabled: Boolean(selectedRoundId) });
  const reportsNeedProcessing = Boolean(
    round.data?.status === "report_pending"
    && round.data.reports.some((report) => report.status === "review_pending"),
  );
  const pendingActions = useQuery({
    queryKey: ["pending-actions", workspaceId],
    queryFn: () => listActions(workspaceId, { status: "pending" }),
    enabled: Boolean(workspace && reportsNeedProcessing),
  });
  const stream = useAgentEvents(round.data?.sessionId ?? null, { onMissingSession: () => { setSelectedRoundId(null); void client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }); } });
  const invalidateRound = async (roundId: string) => Promise.all([client.invalidateQueries({ queryKey: ["review-round", roundId] }), client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }), client.invalidateQueries({ queryKey: ["active-review-questions", workspaceId] })]);
  // Event payloads contain only invalidation metadata; durable messages stay server-owned.
  const eventCount = stream.events.length;
  const evaluatingAttemptId = round.data?.attempts.at(-1)?.status === "evaluating" ? round.data.attempts.at(-1)?.id ?? null : null;
  const evaluationStage = useMemo(
    () => currentEvaluationStage(stream.events, evaluatingAttemptId),
    [stream.events, evaluatingAttemptId],
  );
  useEffect(() => {
    if (eventCount > 0 && selectedRoundId) void invalidateRound(selectedRoundId);
  }, [eventCount, selectedRoundId]);
  useEffect(() => {
    if (!round.data || !["waiting_for_input", "running"].includes(round.data.status)) return;
    focusedWorkspaceRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [round.data?.id]);
  useEffect(() => {
    setViewedOrdinal(null);
  }, [round.data?.id, round.data?.currentIndex]);
  const currentReportAction = pendingActions.data?.find((action) =>
    action.executionId === round.data?.executionId
    && action.actionType === "knowledge.publish"
    && typeof action.preview.draftId === "string"
  ) ?? null;
  const activeApprovalReportId = typeof currentReportAction?.preview.draftId === "string"
    ? currentReportAction.preview.draftId
    : null;
  useEffect(() => {
    setResultPaneMode("split");
    setSelectedReportId(null);
  }, [round.data?.id]);
  useEffect(() => {
    if (!activeApprovalReportId) return;
    if (!selectedReportId) setSelectedReportId(activeApprovalReportId);
  }, [activeApprovalReportId, selectedReportId]);
  const create = useMutation({ mutationFn: createReviewRound, onSuccess: async (value) => { setCreating(false); setSelectedRoundId(value.id); await invalidateRound(value.id); } });
  const answer = useMutation({
    mutationFn: ({ value, key, providerModelId, reasoningEffort }: { value: string; key: string; providerModelId: string; reasoningEffort: "none" | "low" | "medium" | "high" }) => submitReviewAnswer(round.data!, value, key, providerModelId, reasoningEffort),
    onSuccess: async (receipt) => { await invalidateRound(receipt.roundId); setOptimisticMessage(null); },
    onError: () => setOptimisticMessage(null),
  });
  const retry = useMutation({ mutationFn: () => retryReviewEvaluation(round.data!.id, commandId("retry")), onSuccess: async (receipt) => invalidateRound(receipt.roundId) });
  const interrupt = useMutation({ mutationFn: () => interruptReviewEvaluation(round.data!.id, commandId("interrupt-evaluation")), onSuccess: async (value) => invalidateRound(value.id) });
  const recover = useMutation({ mutationFn: () => retryReviewRound(round.data!.id), onSuccess: async (value) => invalidateRound(value.id) });
  const skip = useMutation({ mutationFn: () => skipReviewQuestion(round.data!, commandId("skip")), onSuccess: async (value) => invalidateRound(value.id) });
  const cancel = useMutation({ mutationFn: () => cancelReviewRound(round.data!.id), onSuccess: async (value) => invalidateRound(value.id) });
  const discuss = useMutation({
    mutationFn: (ordinal: number) => createReviewDiscussion(round.data!.id, ordinal),
    onSuccess: async (session, ordinal) => {
      setDiscussionTarget({ sessionId: session.id, ordinal });
      await invalidateRound(round.data!.id);
    },
  });
  const archive = useMutation({ mutationFn: (value: ReviewRound) => archiveReviewRound(value.sessionId), onSuccess: () => client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }) });
  const restore = useMutation({ mutationFn: (value: ReviewRound) => restoreReviewRound(value.sessionId), onSuccess: () => client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }) });
  const busy = create.isPending || answer.isPending || skip.isPending || interrupt.isPending || cancel.isPending || retry.isPending || recover.isPending;
  const caught = create.error ?? answer.error ?? interrupt.error ?? retry.error ?? recover.error ?? skip.error ?? cancel.error ?? discuss.error ?? archive.error ?? restore.error ?? rounds.error ?? round.error;
  const error = caught ? toActionableError(caught, "复习操作失败") : null;

  if (!workspace) return <div className="empty-state"><p>请先初始化工作区</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  async function submitAnswer(value: string, configuration: { providerModelId: string; reasoningEffort: "none" | "low" | "medium" | "high" }) {
    if (!round.data?.currentInput) throw new Error("当前没有待回答输入");
    const key = commandId("answer");
    setOptimisticMessage({ id: key, executionId: round.data.executionId, role: "user", content: value, messageKind: "review_answer", payload: {}, createdAt: new Date().toISOString() });
    await answer.mutateAsync({ value, key, ...configuration });
  }
  const openReportApproval = (reportId?: string) => {
    setSelectedReportId(reportId ?? activeApprovalReportId);
    setResultPaneMode("approval");
    requestAnimationFrame(() => {
      reportApprovalRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      reportApprovalRef.current?.focus();
    });
  };
  const handleReportResolved = async (resolved: PendingAction) => {
    const resolvedDraftId = typeof resolved.preview.draftId === "string" ? resolved.preview.draftId : null;
    setSelectedReportId(resolvedDraftId);
    await invalidateRound(round.data!.id);
  };

  const showRoundMenu = round.data && !["completed", "cancelled", "failed"].includes(round.data.status);
  const toolbarActions = (selectedRoundId || creating) && !discussionTarget ? <>
    <Button variant="ghost" className="review-back" onClick={() => { setSelectedRoundId(null); setCreating(false); setDiscussionTarget(null); }}><ArrowLeft size={16} />返回历史</Button>
    {showRoundMenu ? <details className="review-round-menu"><summary aria-label="更多轮次操作"><MoreHorizontal size={19} /></summary><div><button type="button" className="is-danger" disabled={busy} onClick={() => cancel.mutate()}><StopCircle size={16} />结束本轮</button></div></details> : null}
  </> : null;

  const discussionAttempt = discussionTarget ? round.data?.attempts.find((item) => item.ordinal === discussionTarget.ordinal) ?? null : null;
  const viewedAttempt = viewedOrdinal ? round.data?.attempts.find((item) => item.ordinal === viewedOrdinal) ?? null : null;
  const selectedReport = round.data?.reports.find((report) => report.id === selectedReportId) ?? null;
  const showReportPane = Boolean(round.data && (reportsNeedProcessing || selectedReport));
  const reportQueue = round.data ? (
    <nav className="review-report-queue" aria-label="报告确认顺序">
      {round.data.reports.map((report, index) => {
        const activeIndex = round.data!.reports.findIndex((item) => item.id === activeApprovalReportId);
        const active = report.id === activeApprovalReportId;
        const selected = report.id === (selectedReportId ?? activeApprovalReportId);
        const waitingForPrevious = round.data!.reports
          .slice(0, index)
          .some((item) => !item.publication && item.status === "review_pending");
        const state = report.publication
          ? "已确认"
          : report.status === "rejected"
            ? "已退回"
            : active
              ? "当前待确认"
              : activeIndex >= 0 && index < activeIndex
                ? "已处理"
                : waitingForPrevious
                  ? "等待上一份"
                  : "正在准备";
        return (
          <button
            type="button"
            key={report.id}
            aria-current={selected ? "step" : undefined}
            onClick={() => setSelectedReportId(report.id)}
          >
            <span>{index + 1}</span>
            <div><strong>{report.reportKind === "mastery_report" ? "掌握度更新" : "复习报告"}</strong><small>{state}</small></div>
          </button>
        );
      })}
    </nav>
  ) : null;

  return <ReviewShell section={section} actions={toolbarActions} onSectionChange={(value) => { setSection(value); setSelectedRoundId(null); setCreating(false); setDiscussionTarget(null); }}>
    {section === "catalog" ? <QuestionCatalog workspace={workspace} /> : !selectedRoundId && !creating ? <ReviewLanding rounds={rounds.data ?? []} questionCount={questions.isPending ? null : questions.data?.length ?? 0} onCreate={() => setCreating(true)} onOpen={(id) => { setSelectedRoundId(id); setDiscussionTarget(null); }} onCatalog={() => setSection("catalog")} onArchive={(value) => archive.mutate(value)} onRestore={(value) => restore.mutate(value)} /> : <section className="review-workbench" aria-label="复习工作台">
      <main className="review-workbench__main">
        {creating ? <ReviewSetup workspace={workspace} questions={questions.data ?? []} onCreate={(request) => create.mutate(request)} onCatalog={() => { setSection("catalog"); setCreating(false); }} busy={create.isPending} /> : null}
        {round.isPending && selectedRoundId ? <p className="status-note" role="status">正在恢复复习轮次…</p> : null}
        {!discussionTarget && round.data && ["waiting_for_input", "running"].includes(round.data.status) && round.data.executionStatus !== "failed" ? <><ReviewQuestionStepper round={round.data} viewedOrdinal={viewedOrdinal} onSelect={(ordinal) => setViewedOrdinal(ordinal === round.data!.currentIndex + 1 ? null : ordinal)} />{viewedAttempt ? <ReviewAttemptPreview attempt={viewedAttempt} currentOrdinal={round.data.currentIndex + 1} onBack={() => setViewedOrdinal(null)} /> : <section ref={focusedWorkspaceRef} className="review-focus-workspace"><ReviewConversation round={round.data} optimisticMessage={optimisticMessage} busy={busy} evaluationStage={evaluationStage} onSubmit={submitAnswer} onSkip={() => skip.mutate()} onInterrupt={() => interrupt.mutate()} onRetry={() => retry.mutate()} /><div className="review-insight-column"><ReviewRuntimePanel round={round.data} evaluationStage={evaluationStage} />{round.data.executionStatus === "waiting_for_approval" ? <ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={round.data.executionId} onResolved={() => void invalidateRound(round.data!.id)} /> : null}</div></section>}</> : null}
        {discussionTarget && discussionAttempt && round.data ? (
          <ReviewDiscussion
            roundId={round.data.id}
            sessionId={discussionTarget.sessionId}
            attempt={discussionAttempt}
            defaultModelId={round.data.settings.answer_model_id}
            defaultReasoning={round.data.settings.reasoning_effort}
            onClose={() => setDiscussionTarget(null)}
          />
        ) : (
          <>
            {round.data && (round.data.executionStatus === "failed" || ["cancelled", "failed"].includes(round.data.status)) ? (
              <>
                <ReviewTerminalState round={round.data} recovering={recover.isPending} onRecover={() => recover.mutate()} />
                {round.data.attempts.length ? <ReviewResults round={round.data} discussingOrdinal={discuss.isPending ? discuss.variables ?? null : null} onDiscuss={(ordinal) => discuss.mutate(ordinal)} /> : null}
              </>
            ) : null}
            {round.data && ["report_pending", "completed"].includes(round.data.status) ? (
              <section className={`review-result-workspace${showReportPane ? ` has-approval is-${resultPaneMode}` : ""}`}>
                <button type="button" className="review-pane-rail is-left" aria-label="展开复习结果" onClick={() => setResultPaneMode("split")}>
                  <PanelLeftOpen size={18} /><span>展开复习结果</span>
                </button>
                <ReviewResults
                  round={round.data}
                  discussingOrdinal={discuss.isPending ? discuss.variables ?? null : null}
                  onDiscuss={(ordinal) => discuss.mutate(ordinal)}
                  onOpenApproval={round.data.reports.length ? openReportApproval : undefined}
                  activeApprovalReportId={activeApprovalReportId}
                  selectedReportId={selectedReportId}
                  onCollapse={showReportPane ? () => setResultPaneMode("approval") : undefined}
                />
                <button type="button" className="review-pane-rail is-right" aria-label="展开报告确认" onClick={() => setResultPaneMode("split")}>
                  <PanelRightOpen size={18} /><span>展开报告确认</span>
                </button>
                {showReportPane ? (
                  <aside ref={reportApprovalRef} tabIndex={-1} className="review-result-approval" aria-label="报告确认区">
                    {selectedReport && (selectedReport.publication || selectedReport.status !== "review_pending") ? (
                      <ReviewReportViewer
                        report={selectedReport}
                        queue={reportQueue}
                        nextReportId={activeApprovalReportId && activeApprovalReportId !== selectedReport.id ? activeApprovalReportId : null}
                        onSelect={setSelectedReportId}
                        onCollapse={() => setResultPaneMode("results")}
                      />
                    ) : (
                      <ActionCenter
                        workspaceId={workspace.id}
                        showDiagnostic={false}
                        actionType="knowledge.publish"
                        watchExecutionId={round.data.executionId}
                        presentation="review-report"
                        preferredDraftId={selectedReportId ?? activeApprovalReportId}
                        headerContent={reportQueue}
                        headerActions={(
                          <button type="button" className="review-pane-collapse" aria-label="收起报告确认，展开复习结果" title="收起报告确认" onClick={() => setResultPaneMode("results")}>
                            <PanelRightClose size={18} />
                          </button>
                        )}
                        onResolved={(resolved) => void handleReportResolved(resolved)}
                      />
                    )}
                  </aside>
                ) : null}
              </section>
            ) : null}
          </>
        )}
        {error || (stream.executionError && round.data?.executionStatus !== "failed") ? <div className="error-banner" role="alert"><AlertCircle size={16} /><span>错误：{error?.message ?? stream.executionError?.message}</span><span>{error?.advice ?? "刷新轮次后重试"}</span></div> : null}
      </main>
    </section>}
  </ReviewShell>;
}
