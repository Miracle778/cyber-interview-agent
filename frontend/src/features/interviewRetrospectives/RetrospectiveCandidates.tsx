import { useMemo, useState } from "react";
import { ArrowRight, BookOpenCheck, CheckCircle2, CircleAlert, Layers3, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type {
  InterviewQuestion,
  RetrospectiveCandidate,
  RetrospectiveCandidateDecision,
} from "./retrospectiveTypes";

type CandidateGroup = "review" | "profile" | "summary";

const GROUPS: Array<{ id: CandidateGroup; label: string; icon: typeof BookOpenCheck }> = [
  { id: "review", label: "复习题", icon: BookOpenCheck },
  { id: "profile", label: "项目与画像", icon: Layers3 },
  { id: "summary", label: "复盘总结", icon: Sparkles },
];

function groupOf(candidate: RetrospectiveCandidate): CandidateGroup {
  if (candidate.candidateKind === "review_question") return "review";
  if (candidate.candidateKind === "summary") return "summary";
  return "profile";
}

function candidateTitle(candidate: RetrospectiveCandidate, questions: InterviewQuestion[]) {
  const question = questions.find((item) => item.id === candidate.questionUnitId);
  if (question) return question.questionText;
  const title = candidate.payload.title;
  return typeof title === "string" ? title : "本场复盘总结";
}

function candidateDescription(candidate: RetrospectiveCandidate) {
  if (candidate.candidateKind === "review_question") {
    const answer = candidate.payload.suggestedAnswer;
    return typeof answer === "string" && answer ? answer : "将这道问题送入后续复习。";
  }
  if (candidate.candidateKind === "project_narrative") {
    const narrative = candidate.payload.suggestedNarrative;
    return typeof narrative === "string" && narrative ? narrative : "把这次回答整理成项目讲解建议。";
  }
  if (candidate.candidateKind === "profile_claim") return "把确认后的事实作为画像更新建议。";
  return "选择是否把本场确认内容整理为可发布复盘。";
}

export function RetrospectiveCandidates({
  retrospectiveId,
  candidates,
  questions,
  busy,
  onDecision,
  onBatchDecision,
}: {
  retrospectiveId: string;
  candidates: RetrospectiveCandidate[];
  questions: InterviewQuestion[];
  busy: boolean;
  onDecision: (
    candidate: RetrospectiveCandidate,
    action: RetrospectiveCandidateDecision,
    targetResourceId?: string,
  ) => void;
  onBatchDecision: (candidates: RetrospectiveCandidate[]) => void;
}) {
  const [group, setGroup] = useState<CandidateGroup>("review");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const grouped = useMemo(
    () => Object.fromEntries(GROUPS.map((item) => [item.id, candidates.filter((candidate) => groupOf(candidate) === item.id)])) as Record<CandidateGroup, RetrospectiveCandidate[]>,
    [candidates],
  );
  const visible = grouped[group];
  const selected = candidates.filter((item) => selectedIds.includes(item.id) && ["pending", "failed"].includes(item.status));
  const pendingInferred = questions.filter((item) => item.origin === "inferred" && item.decisionStatus === "pending").length;

  function toggle(candidate: RetrospectiveCandidate) {
    setSelectedIds((current) => current.includes(candidate.id) ? current.filter((id) => id !== candidate.id) : [...current, candidate.id]);
  }

  return (
    <section className="retrospective-candidates" aria-labelledby="retrospective-candidates-title">
      <header className="retrospective-candidates__header">
        <div>
          <p>确认后再进入准备资料</p>
          <h3 id="retrospective-candidates-title">沉淀本次复盘</h3>
          <span>系统只整理候选，不会自动改写题库、画像或项目资料。</span>
        </div>
        <strong>{candidates.filter((item) => item.status === "pending").length} 项待确认</strong>
      </header>
      {pendingInferred ? (
        <div className="retrospective-candidates__inference" role="status">
          <CircleAlert size={18} />
          <span>还有 {pendingInferred} 道推断题待确认，它们暂时不会生成沉淀候选。</span>
        </div>
      ) : null}
      <div className="retrospective-candidates__groups" role="tablist" aria-label="候选资料分组">
        {GROUPS.map((item) => (
          <button key={item.id} type="button" role="tab" aria-selected={group === item.id} onClick={() => setGroup(item.id)}>
            <item.icon size={17} />
            <span>{item.label}</span>
            <strong>{grouped[item.id].length}</strong>
          </button>
        ))}
      </div>
      <div className="retrospective-candidates__list" role="tabpanel" aria-label={GROUPS.find((item) => item.id === group)?.label}>
        {visible.length ? visible.map((candidate) => {
          const title = candidateTitle(candidate, questions);
          const actionable = ["pending", "failed"].includes(candidate.status);
          return (
            <article key={candidate.id} className="retrospective-candidate" data-status={candidate.status}>
              <label className="retrospective-candidate__select">
                <input type="checkbox" aria-label={`选择候选：${title}`} checked={selectedIds.includes(candidate.id)} disabled={!actionable || busy} onChange={() => toggle(candidate)} />
              </label>
              <div className="retrospective-candidate__body">
                <header>
                  <div><h4>{title}</h4><p>{candidateDescription(candidate)}</p></div>
                  <CandidateStatus candidate={candidate} />
                </header>
                {candidate.lastErrorCode ? <p className="retrospective-candidate__error" role="alert">上次处理未完成：{candidate.lastErrorCode}</p> : null}
                {actionable ? <CandidateActions candidate={candidate} busy={busy} onDecision={onDecision} /> : null}
                {candidate.status === "confirmed" && candidate.targetResourceType === "review_question" && candidate.targetResourceId ? (
                  <Link className="retrospective-candidate__practice" to={`/review?questionId=${encodeURIComponent(candidate.targetResourceId)}&source=retrospective&id=${encodeURIComponent(retrospectiveId)}`}>
                    立即练习 <ArrowRight size={16} />
                  </Link>
                ) : null}
              </div>
            </article>
          );
        }) : <div className="retrospective-candidates__empty"><CheckCircle2 size={24} /><strong>这一组暂时没有候选</strong><p>完成分析或确认推断题后，这里会自动更新。</p></div>}
      </div>
      {selected.length ? (
        <footer className="retrospective-candidates__batch" aria-live="polite">
          <span>已选 {selected.length} 项，只处理当前明确选择。</span>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onBatchDecision(selected)}>批量暂不沉淀 {selected.length} 项</Button>
        </footer>
      ) : null}
    </section>
  );
}

function CandidateStatus({ candidate }: { candidate: RetrospectiveCandidate }) {
  const labels = {
    pending: "待确认",
    confirmed: candidate.targetResourceType === "review_question_candidate" ? "已送题库确认" : "已处理",
    rejected: "已忽略",
    blocked: "暂时受阻",
    failed: "处理失败",
    superseded: "已被新版本替代",
  };
  return <span className="retrospective-candidate__status" data-status={candidate.status}>{labels[candidate.status]}</span>;
}

function CandidateActions({ candidate, busy, onDecision }: {
  candidate: RetrospectiveCandidate;
  busy: boolean;
  onDecision: (
    candidate: RetrospectiveCandidate,
    action: RetrospectiveCandidateDecision,
    targetResourceId?: string,
  ) => void;
}) {
  if (candidate.candidateKind === "review_question") {
    return <div className="retrospective-candidate__actions">
      {candidate.matches.slice(0, 2).map((match) => <Button key={match.resourceId} size="sm" variant="secondary" disabled={busy} aria-label={`关联已有题：${match.title ?? match.resourceId}`} onClick={() => onDecision(candidate, "link_existing", match.resourceId)}>关联已有题 · {Math.round(match.score * 100)}%</Button>)}
      <Button size="sm" disabled={busy} onClick={() => onDecision(candidate, "create_new")}>新建复习题</Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecision(candidate, "reject")}>暂不沉淀</Button>
    </div>;
  }
  if (candidate.candidateKind === "summary") {
    return <div className="retrospective-candidate__actions"><Button size="sm" disabled={busy} onClick={() => onDecision(candidate, "include")}>纳入复盘总结</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecision(candidate, "exclude")}>不纳入</Button></div>;
  }
  return <div className="retrospective-candidate__actions">
    {candidate.matches.slice(0, 2).map((match) => <Button key={match.resourceId} size="sm" variant="secondary" disabled={busy} onClick={() => onDecision(candidate, "propose_update", match.resourceId)}>生成更新建议</Button>)}
    <Button size="sm" disabled={busy} onClick={() => onDecision(candidate, "propose_new")}>生成新建议</Button>
    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecision(candidate, "reject")}>暂不沉淀</Button>
  </div>;
}
