import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, MoreHorizontal, RotateCcw, StopCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { toActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import { useAgentEvents } from "../agent/useAgentEvents";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { archiveReviewRound, cancelReviewRound, createReviewDiscussion, createReviewRound, getReviewRound, listActiveQuestions, listReviewRounds, restoreReviewRound, retryReviewEvaluation, retryReviewRound, skipReviewQuestion, submitReviewAnswer } from "./reviewApi";
import { QuestionCatalog } from "./QuestionCatalog";
import { ReviewConversation } from "./ReviewConversation";
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

function ReviewQuestionStepper({ round }: { round: ReviewRound }) {
  const current = Math.min(round.currentIndex, Math.max(0, round.questionCount - 1));
  const all = Array.from({ length: round.questionCount }, (_, index) => index);
  const indexes = round.questionCount <= 5 ? all : [...new Set([0, Math.max(0, current - 1), current, Math.min(round.questionCount - 1, current + 1), round.questionCount - 1])].sort((left, right) => left - right);
  const attemptTitle = (index: number) => round.attempts.find((item) => item.ordinal === index + 1)?.questionSnapshot.title;
  return <nav className="review-question-stepper" aria-label="本轮题目进度">
    <ol>{indexes.map((index, position) => {
      const title = index === current ? round.currentQuestion?.title : attemptTitle(index);
      const completed = index < current || round.status === "completed";
      return <li key={index} aria-current={index === current ? "step" : undefined} data-completed={completed || undefined}>
        {position > 0 && indexes[position - 1] !== index - 1 ? <span className="review-question-stepper__ellipsis" aria-hidden="true">…</span> : null}
        <span className="review-question-stepper__number">{index + 1}</span>
        <span><small>{index === current ? `第 ${index + 1} / ${round.questionCount} 题` : `第 ${index + 1} 题`}</small><strong>{title ?? "待开始"}</strong></span>
      </li>;
    })}</ol>
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

export function ReviewPage({ workspace }: ReviewPageProps) {
  const client = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const [section, setSection] = useState<ReviewSection>("practice");
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [optimisticMessage, setOptimisticMessage] = useState<ReviewTimelineMessage | null>(null);
  const [discussionTarget, setDiscussionTarget] = useState<{ sessionId: string; ordinal: number } | null>(null);
  const focusedWorkspaceRef = useRef<HTMLElement | null>(null);
  const rounds = useQuery({ queryKey: ["review-rounds", workspaceId], queryFn: () => listReviewRounds(workspaceId), enabled: Boolean(workspace) });
  const questions = useQuery({ queryKey: ["active-review-questions", workspaceId], queryFn: () => listActiveQuestions(workspaceId), enabled: Boolean(workspace) });
  const round = useQuery({ queryKey: ["review-round", selectedRoundId], queryFn: () => getReviewRound(selectedRoundId!), enabled: Boolean(selectedRoundId) });
  const stream = useAgentEvents(round.data?.sessionId ?? null, { onMissingSession: () => { setSelectedRoundId(null); void client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }); } });
  const invalidateRound = async (roundId: string) => Promise.all([client.invalidateQueries({ queryKey: ["review-round", roundId] }), client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }), client.invalidateQueries({ queryKey: ["active-review-questions", workspaceId] })]);
  // Event payloads contain only invalidation metadata; durable messages stay server-owned.
  const eventCount = stream.events.length;
  useEffect(() => {
    if (eventCount > 0 && selectedRoundId) void invalidateRound(selectedRoundId);
  }, [eventCount, selectedRoundId]);
  useEffect(() => {
    if (!round.data || !["waiting_for_input", "running"].includes(round.data.status)) return;
    focusedWorkspaceRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [round.data?.id]);
  const create = useMutation({ mutationFn: createReviewRound, onSuccess: async (value) => { setCreating(false); setSelectedRoundId(value.id); await invalidateRound(value.id); } });
  const answer = useMutation({
    mutationFn: ({ value, key, providerModelId, reasoningEffort }: { value: string; key: string; providerModelId: string; reasoningEffort: "none" | "low" | "medium" | "high" }) => submitReviewAnswer(round.data!, value, key, providerModelId, reasoningEffort),
    onSuccess: async (receipt) => { await invalidateRound(receipt.roundId); setOptimisticMessage(null); },
    onError: () => setOptimisticMessage(null),
  });
  const retry = useMutation({ mutationFn: () => retryReviewEvaluation(round.data!.id, commandId("retry")), onSuccess: async (receipt) => invalidateRound(receipt.roundId) });
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
  const busy = create.isPending || answer.isPending || skip.isPending || cancel.isPending || retry.isPending || recover.isPending;
  const caught = create.error ?? answer.error ?? retry.error ?? recover.error ?? skip.error ?? cancel.error ?? discuss.error ?? archive.error ?? restore.error ?? rounds.error ?? round.error;
  const error = caught ? toActionableError(caught, "复习操作失败") : null;

  if (!workspace) return <div className="empty-state"><p>请先初始化工作区</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  async function submitAnswer(value: string, configuration: { providerModelId: string; reasoningEffort: "none" | "low" | "medium" | "high" }) {
    if (!round.data?.currentInput) throw new Error("当前没有待回答输入");
    const key = commandId("answer");
    setOptimisticMessage({ id: key, executionId: round.data.executionId, role: "user", content: value, messageKind: "review_answer", payload: {}, createdAt: new Date().toISOString() });
    await answer.mutateAsync({ value, key, ...configuration });
  }

  const showRoundMenu = round.data && !["completed", "cancelled", "failed"].includes(round.data.status);
  const toolbarActions = (selectedRoundId || creating) && !discussionTarget ? <>
    <Button variant="ghost" className="review-back" onClick={() => { setSelectedRoundId(null); setCreating(false); setDiscussionTarget(null); }}><ArrowLeft size={16} />返回历史</Button>
    {showRoundMenu ? <details className="review-round-menu"><summary aria-label="更多轮次操作"><MoreHorizontal size={19} /></summary><div><button type="button" className="is-danger" disabled={busy} onClick={() => cancel.mutate()}><StopCircle size={16} />结束本轮</button></div></details> : null}
  </> : null;

  const discussionAttempt = discussionTarget ? round.data?.attempts.find((item) => item.ordinal === discussionTarget.ordinal) ?? null : null;

  return <ReviewShell section={section} actions={toolbarActions} onSectionChange={(value) => { setSection(value); setSelectedRoundId(null); setCreating(false); setDiscussionTarget(null); }}>
    {section === "catalog" ? <QuestionCatalog workspace={workspace} /> : !selectedRoundId && !creating ? <ReviewLanding rounds={rounds.data ?? []} questionCount={questions.isPending ? null : questions.data?.length ?? 0} onCreate={() => setCreating(true)} onOpen={(id) => { setSelectedRoundId(id); setDiscussionTarget(null); }} onCatalog={() => setSection("catalog")} onArchive={(value) => archive.mutate(value)} onRestore={(value) => restore.mutate(value)} /> : <section className="review-workbench" aria-label="复习工作台">
      <main className="review-workbench__main">
        {creating ? <ReviewSetup workspace={workspace} questions={questions.data ?? []} onCreate={(request) => create.mutate(request)} onCatalog={() => { setSection("catalog"); setCreating(false); }} busy={create.isPending} /> : null}
        {round.isPending && selectedRoundId ? <p className="status-note" role="status">正在恢复复习轮次…</p> : null}
        {!discussionTarget && round.data && ["waiting_for_input", "running"].includes(round.data.status) && round.data.executionStatus !== "failed" ? <><ReviewQuestionStepper round={round.data} /><section ref={focusedWorkspaceRef} className="review-focus-workspace"><ReviewConversation round={round.data} optimisticMessage={optimisticMessage} busy={busy} onSubmit={submitAnswer} onSkip={() => skip.mutate()} onRetry={() => retry.mutate()} /><div className="review-insight-column"><ReviewRuntimePanel round={round.data} />{round.data.executionStatus === "waiting_for_approval" ? <ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={round.data.executionId} onResolved={() => void invalidateRound(round.data!.id)} /> : null}</div></section></> : null}
        {discussionTarget && discussionAttempt && round.data ? <ReviewDiscussion roundId={round.data.id} sessionId={discussionTarget.sessionId} attempt={discussionAttempt} defaultModelId={round.data.settings.answer_model_id} defaultReasoning={round.data.settings.reasoning_effort} onClose={() => setDiscussionTarget(null)} /> : <>{round.data && (round.data.executionStatus === "failed" || ["cancelled", "failed"].includes(round.data.status)) ? <><ReviewTerminalState round={round.data} recovering={recover.isPending} onRecover={() => recover.mutate()} />{round.data.attempts.length ? <ReviewResults round={round.data} discussingOrdinal={discuss.isPending ? discuss.variables ?? null : null} onDiscuss={(ordinal) => discuss.mutate(ordinal)} /> : null}</> : null}{round.data && ["report_pending", "completed"].includes(round.data.status) ? <ReviewResults round={round.data} discussingOrdinal={discuss.isPending ? discuss.variables ?? null : null} onDiscuss={(ordinal) => discuss.mutate(ordinal)} /> : null}</>}
        {error || (stream.executionError && round.data?.executionStatus !== "failed") ? <div className="error-banner" role="alert"><AlertCircle size={16} /><span>错误：{error?.message ?? stream.executionError?.message}</span><span>{error?.advice ?? "刷新轮次后重试"}</span></div> : null}
      </main>
    </section>}
  </ReviewShell>;
}
