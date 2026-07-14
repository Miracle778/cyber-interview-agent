import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { toActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import { useAgentEvents } from "../agent/useAgentEvents";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { cancelReviewRound, createReviewDiscussion, createReviewRound, getReviewRound, listActiveQuestions, listReviewRounds, retryReviewEvaluation, skipReviewQuestion, submitReviewAnswer } from "./reviewApi";
import { QuestionCatalog } from "./QuestionCatalog";
import { ReviewConversation } from "./ReviewConversation";
import { ReviewHistory } from "./ReviewHistory";
import { ReviewLanding } from "./ReviewLanding";
import { ReviewResults } from "./ReviewResults";
import { ReviewRuntimePanel } from "./ReviewRuntimePanel";
import { ReviewSetup } from "./ReviewSetup";
import { ReviewShell, type ReviewSection } from "./ReviewShell";
import type { ReviewQuestion, ReviewTimelineMessage } from "./reviewTypes";

interface ReviewPageProps { workspace: WorkspaceConfig | null; draftQuestion?: ReviewQuestion | null; }

function commandId(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

export function ReviewPage({ workspace }: ReviewPageProps) {
  const client = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const [section, setSection] = useState<ReviewSection>("practice");
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [optimisticMessage, setOptimisticMessage] = useState<ReviewTimelineMessage | null>(null);
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
  const create = useMutation({ mutationFn: createReviewRound, onSuccess: async (value) => { setCreating(false); setSelectedRoundId(value.id); await invalidateRound(value.id); } });
  const answer = useMutation({
    mutationFn: ({ value, key }: { value: string; key: string }) => submitReviewAnswer(round.data!, value, key),
    onSuccess: async (receipt) => { await invalidateRound(receipt.roundId); setOptimisticMessage(null); },
    onError: () => setOptimisticMessage(null),
  });
  const retry = useMutation({ mutationFn: () => retryReviewEvaluation(round.data!.id, commandId("retry")), onSuccess: async (receipt) => invalidateRound(receipt.roundId) });
  const skip = useMutation({ mutationFn: () => skipReviewQuestion(round.data!, commandId("skip")), onSuccess: async (value) => invalidateRound(value.id) });
  const cancel = useMutation({ mutationFn: () => cancelReviewRound(round.data!.id), onSuccess: async (value) => invalidateRound(value.id) });
  const discuss = useMutation({ mutationFn: (ordinal: number) => createReviewDiscussion(round.data!.id, ordinal, "请结合本次回答解释遗漏点，并给一个迁移应用示例。") });
  const busy = create.isPending || answer.isPending || skip.isPending || cancel.isPending || retry.isPending;
  const caught = create.error ?? answer.error ?? retry.error ?? skip.error ?? cancel.error ?? discuss.error ?? rounds.error ?? round.error;
  const error = caught ? toActionableError(caught, "复习操作失败") : null;

  if (!workspace) return <div className="empty-state"><p>请先初始化工作区</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  async function submitAnswer(value: string) {
    if (!round.data?.currentInput) throw new Error("当前没有待回答输入");
    const key = commandId("answer");
    setOptimisticMessage({ id: key, executionId: round.data.executionId, role: "user", content: value, messageKind: "review_answer", payload: {}, createdAt: new Date().toISOString() });
    await answer.mutateAsync({ value, key });
  }

  return <ReviewShell section={section} onSectionChange={(value) => { setSection(value); setSelectedRoundId(null); setCreating(false); }}>
    {section === "catalog" ? <QuestionCatalog workspace={workspace} /> : !selectedRoundId && !creating ? <ReviewLanding rounds={rounds.data ?? []} onCreate={() => setCreating(true)} onOpen={setSelectedRoundId} /> : <section className="review-workbench" aria-label="复习工作台">
      <ReviewHistory rounds={rounds.data ?? []} selectedId={selectedRoundId} onSelect={(id) => { setCreating(false); setSelectedRoundId(id); }} />
      <main className="review-workbench__main">
        <Button variant="ghost" className="review-back" onClick={() => { setSelectedRoundId(null); setCreating(false); }}><ArrowLeft size={16} />返回历史</Button>
        {creating ? <ReviewSetup workspace={workspace} questions={questions.data ?? []} onCreate={(request) => create.mutate(request)} busy={create.isPending} /> : null}
        {round.data && ["waiting_for_input", "running"].includes(round.data.status) ? <ReviewConversation round={round.data} optimisticMessage={optimisticMessage} busy={busy} onSubmit={submitAnswer} onSkip={() => skip.mutate()} onCancel={() => cancel.mutate()} onRetry={() => retry.mutate()} /> : null}
        {round.data && ["report_pending", "completed"].includes(round.data.status) ? <ReviewResults round={round.data} onDiscuss={(ordinal) => discuss.mutate(ordinal)} /> : null}
        {error || stream.executionError ? <div className="error-banner" role="alert"><AlertCircle size={16} /><span>错误：{error?.message ?? stream.executionError?.message}</span><span>{error?.advice ?? "刷新轮次后重试"}</span></div> : null}
      </main>
      <div><ReviewRuntimePanel round={round.data ?? null} />{round.data?.executionStatus === "waiting_for_approval" ? <ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={round.data.executionId} onResolved={() => void invalidateRound(round.data!.id)} /> : null}</div>
    </section>}
  </ReviewShell>;
}
