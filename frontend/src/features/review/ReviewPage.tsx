import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Activity, Brain, FileCheck2, Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import { useAgentEvents } from "../agent/useAgentEvents";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { cancelReviewRound, createReviewDiscussion, createReviewRound, getReviewRound, listActiveQuestions, listReviewRounds, skipReviewQuestion, submitReviewAnswer } from "./reviewApi";
import { QuestionCatalog } from "./QuestionCatalog";
import { ReviewHistory } from "./ReviewHistory";
import { ReviewResults } from "./ReviewResults";
import { ReviewRound } from "./ReviewRound";
import { ReviewSetup } from "./ReviewSetup";
import { ReviewShell, type ReviewSection } from "./ReviewShell";
import type { ReviewQuestion } from "./reviewTypes";

interface ReviewPageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion?: ReviewQuestion | null;
}

export function ReviewPage({ workspace }: ReviewPageProps) {
  const client = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const [section, setSection] = useState<ReviewSection>("practice");
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const rounds = useQuery({ queryKey: ["review-rounds", workspaceId], queryFn: () => listReviewRounds(workspaceId), enabled: Boolean(workspace) });
  const questions = useQuery({ queryKey: ["active-review-questions", workspaceId], queryFn: () => listActiveQuestions(workspaceId), enabled: Boolean(workspace) });
  useEffect(() => { if (!selectedRoundId && rounds.data?.[0]) setSelectedRoundId(rounds.data[0].id); }, [rounds.data, selectedRoundId]);
  const round = useQuery({ queryKey: ["review-round", selectedRoundId], queryFn: () => getReviewRound(selectedRoundId!), enabled: Boolean(selectedRoundId) });
  const stream = useAgentEvents(round.data?.sessionId ?? null, { onMissingSession: () => { setSelectedRoundId(null); void client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }); } });
  useEffect(() => { if (stream.events.length > 0 && selectedRoundId) { void client.invalidateQueries({ queryKey: ["review-round", selectedRoundId] }); void client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] }); void client.invalidateQueries({ queryKey: ["active-review-questions", workspaceId] }); } }, [stream.events.length, selectedRoundId, client, workspaceId]);
  const refresh = async (value: { id: string }) => { setSelectedRoundId(value.id); await Promise.all([client.invalidateQueries({ queryKey: ["review-round", value.id] }), client.invalidateQueries({ queryKey: ["review-rounds", workspaceId] })]); };
  const create = useMutation({ mutationFn: createReviewRound, onSuccess: refresh });
  const answer = useMutation({ mutationFn: ({ value, key }: { value: string; key: string }) => submitReviewAnswer(round.data!, value, key), onSuccess: refresh });
  const skip = useMutation({ mutationFn: () => skipReviewQuestion(round.data!, `skip-${round.data!.currentInput!.id}-${Date.now()}`), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => cancelReviewRound(round.data!.id), onSuccess: refresh });
  const discuss = useMutation({ mutationFn: (ordinal: number) => createReviewDiscussion(round.data!.id, ordinal, "请结合本次回答解释遗漏点，并给一个迁移应用示例。") });
  const busy = create.isPending || answer.isPending || skip.isPending || cancel.isPending;
  const caught = create.error ?? answer.error ?? skip.error ?? cancel.error ?? discuss.error ?? rounds.error ?? round.error;
  const error = caught ? toActionableError(caught, "复习操作失败") : null;

  if (!workspace) return <div className="empty-state"><p>请先初始化工作区</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  return (
    <ReviewShell section={section} onSectionChange={setSection}>
      {section === "catalog" ? <QuestionCatalog workspace={workspace} /> : (
        <section className="review-workbench" aria-label="复习工作台">
          <ReviewHistory rounds={rounds.data ?? []} selectedId={selectedRoundId} onSelect={setSelectedRoundId} />
          <main className="review-workbench__main">
            {!round.data || ["cancelled", "failed"].includes(round.data.status) ? <ReviewSetup workspace={workspace} questions={questions.data ?? []} onCreate={(request) => create.mutate(request)} busy={create.isPending} /> : null}
            {round.data && ["waiting_for_input", "running"].includes(round.data.status) ? <ReviewRound round={round.data} busy={busy} onSubmit={(value) => answer.mutateAsync({ value, key: `answer-${round.data!.currentInput!.id}-${Date.now()}` })} onSkip={() => skip.mutate()} onCancel={() => cancel.mutate()} /> : null}
            {round.data && ["report_pending", "completed"].includes(round.data.status) ? <ReviewResults round={round.data} onDiscuss={(ordinal) => discuss.mutate(ordinal)} /> : null}
            {error || stream.executionError ? <div className="error-banner" role="alert"><AlertCircle size={16} /><span>错误：{error?.message ?? stream.executionError?.message}</span><span>{error?.advice ?? "刷新轮次后重试"}</span></div> : null}
          </main>
          <aside className="review-runtime-panel" aria-label="轮次运行状态">
            <div className="review-pane-title"><Activity size={16} /><strong>运行状态</strong></div>
            {round.data ? <><dl className="runtime-facts"><div><dt>轮次</dt><dd>{round.data.currentIndex}/{round.data.questionCount}</dd></div><div><dt>状态</dt><dd>{round.data.status}</dd></div><div><dt>模型</dt><dd>{round.data.settings.answer_model_id}</dd></div><div><dt>思考强度</dt><dd>{round.data.settings.reasoning_effort}</dd></div></dl><div className="runtime-meter"><Gauge size={16} /><span>{round.data.usage.totalTokens} tokens · {round.data.usage.callCount} calls</span></div><div className="runtime-meter"><Brain size={16} /><span>{round.data.attempts.filter((item) => item.masterySuggestion === "stable" || item.masterySuggestion === "strong").length} 项稳定掌握</span></div><div className="runtime-meter"><FileCheck2 size={16} /><span>{round.data.executionStatus === "waiting_for_approval" ? "报告等待确认" : "产物随轮次生成"}</span></div></> : <p className="status-note">创建轮次后显示模型、用量和掌握度。</p>}
            {round.data?.executionStatus === "waiting_for_approval" ? <ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={round.data.executionId} onResolved={() => { void client.invalidateQueries({ queryKey: ["review-round", round.data!.id] }); }} /> : null}
          </aside>
        </section>
      )}
    </ReviewShell>
  );
}
