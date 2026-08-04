import { useState } from "react";
import { MessageCircle } from "lucide-react";
import { AnalysisProgress } from "./AnalysisProgress";
import { QuestionAnalysisPanel } from "./QuestionAnalysisPanel";
import { QuestionTimeline } from "./QuestionTimeline";
import { RetrospectiveActions } from "./RetrospectiveActions";
import { RetrospectiveCandidates } from "./RetrospectiveCandidates";
import { RetrospectiveConversation } from "./RetrospectiveConversation";
import { Button } from "../../shared/ui/Button";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type {
  AnalysisReport,
  InterviewRetrospective,
  PublicationSection,
  RetrospectiveActionItem,
  RetrospectiveCandidate,
  RetrospectiveCandidateDecision,
  RetrospectivePublicationDraft,
  TranscriptCorrection,
} from "./retrospectiveTypes";

type WorkspaceView = "analysis" | "assets" | "actions";

export function RetrospectiveWorkspace({ retrospective, report, corrections = [], candidates, actions, publicationDraft, selectedQuestionId, focusMode = false, busy, candidateBusy, actionBusy, publicationBusy, onSelectQuestion, onStop, onResume, onRetry, onDecision, onCandidateDecision, onBatchCandidateDecision, onActionDecision, onCreateDraft, onCorrectionConfirmed }: {
  retrospective: InterviewRetrospective;
  report: AnalysisReport;
  corrections?: TranscriptCorrection[];
  candidates: RetrospectiveCandidate[];
  actions: RetrospectiveActionItem[];
  publicationDraft: RetrospectivePublicationDraft | null;
  selectedQuestionId: string | null;
  focusMode?: boolean;
  busy: boolean;
  candidateBusy: boolean;
  actionBusy: boolean;
  publicationBusy: boolean;
  onSelectQuestion: (id: string) => void;
  onStop: () => void;
  onResume: () => void;
  onRetry: () => void;
  onDecision: (decision: "confirmed" | "rejected") => void;
  onCandidateDecision: (candidate: RetrospectiveCandidate, decision: RetrospectiveCandidateDecision, targetResourceId?: string) => void;
  onBatchCandidateDecision: (candidates: RetrospectiveCandidate[]) => void;
  onActionDecision: (action: RetrospectiveActionItem, decision: "completed" | "dismissed") => void;
  onCreateDraft: (sections: PublicationSection[]) => void;
  onCorrectionConfirmed?: () => void;
}) {
  const [view, setView] = useState<WorkspaceView>("analysis");
  const [conversationOpen, setConversationOpen] = useState(false);
  const question = report.questions.find((item) => item.id === selectedQuestionId) ?? report.questions[0] ?? null;
  const analysis = report.analyses.find((item) => item.questionUnitId === question?.id) ?? null;
  const item = report.items.find((candidate) => candidate.questionUnitId === question?.id) ?? null;
  const adoptedCorrections = corrections.filter((correction) =>
    ["auto_accepted", "accepted", "manual"].includes(correction.decision)
      && correction.adoptedText !== correction.originalText,
  );
  const returnTo = `/retrospectives?retrospectiveId=${encodeURIComponent(retrospective.id)}${question ? `&questionId=${encodeURIComponent(question.id)}` : ""}`;
  return <div className={`retrospective-workbench${focusMode ? " retrospective-workbench--focused" : ""}`}>
    {!focusMode ? <header className="retrospective-workbench__header"><div><p>{retrospective.roundLabel}</p><h2 id="retrospective-workbench-title">{retrospective.title}</h2></div><div className="retrospective-workbench__header-actions"><Button variant="secondary" onClick={() => setConversationOpen(true)}><MessageCircle size={16} />讨论与纠正</Button></div></header> : null}
    <AnalysisProgress run={report.analysisRun} items={report.items} busy={busy} onStop={onStop} onResume={onResume} onRetry={onRetry} />
    {adoptedCorrections.length ? <details className="retrospective-revisions">
      <summary>已修订 {adoptedCorrections.length} 处 · 查看原文对照</summary>
      <div className="retrospective-revisions__list">
        {adoptedCorrections.map((correction) => <article key={correction.id}>
          <div><span>原文</span><p>{correction.originalText || "原文已清除"}</p></div>
          <div><span>采用</span><p>{correction.adoptedText || "未保留修订正文"}</p></div>
          {correction.reason ? <small>{correction.reason}</small> : null}
        </article>)}
      </div>
    </details> : null}
    <div className="retrospective-workbench__navigation"><nav className="retrospective-workbench__views" role="tablist" aria-label="复盘工作区">
        <button type="button" role="tab" aria-selected={view === "analysis"} onClick={() => setView("analysis")}>逐题复盘 <span>{report.questions.length}</span></button>
        <button type="button" role="tab" aria-selected={view === "assets"} onClick={() => setView("assets")}>准备资产 <span>{candidates.filter((candidate) => ["pending", "failed"].includes(candidate.status)).length}</span></button>
        <button type="button" role="tab" aria-selected={view === "actions"} onClick={() => setView("actions")}>行动与发布 <span>{actions.filter((action) => action.status === "pending").length}</span></button>
      </nav>{focusMode ? <Button size="sm" variant="secondary" onClick={() => setConversationOpen(true)}><MessageCircle size={15} />讨论与纠正</Button> : null}</div>
    {view === "analysis" ? <TaskWorkspace className="retrospective-workbench__workspace" labelledBy="retrospective-question-list-title">
        <TaskWorkspacePane className="retrospective-workbench__timeline" aria-label="面试问题列表">
          <QuestionTimeline questions={report.questions} analyses={report.analyses} items={report.items} selectedId={question?.id ?? null} onSelect={onSelectQuestion} />
        </TaskWorkspacePane>
        <TaskWorkspacePane className="retrospective-workbench__analysis" aria-label="问题分析详情">
          <QuestionAnalysisPanel question={question} analysis={analysis} item={item} executionId={report.analysisRun.executionId} returnTo={returnTo} busy={busy} onDecision={onDecision} />
        </TaskWorkspacePane>
      </TaskWorkspace> : <div className="retrospective-workbench__secondary" role="tabpanel">
        {view === "assets" ? <RetrospectiveCandidates retrospectiveId={retrospective.id} candidates={candidates} questions={report.questions} busy={candidateBusy} onDecision={onCandidateDecision} onBatchDecision={onBatchCandidateDecision} /> : null}
        {view === "actions" ? <RetrospectiveActions actions={actions} busy={actionBusy || publicationBusy} draft={publicationDraft} onDecision={onActionDecision} onCreateDraft={onCreateDraft} /> : null}
      </div>}
    {conversationOpen ? <RetrospectiveConversation workspaceId={retrospective.workspaceId} retrospectiveId={retrospective.id} selectedQuestionId={question?.id ?? null} selectedQuestionText={question?.questionText ?? null} onClose={() => setConversationOpen(false)} onCorrectionConfirmed={onCorrectionConfirmed} /> : null}
  </div>;
}
