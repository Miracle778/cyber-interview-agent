import { AnalysisProgress } from "./AnalysisProgress";
import { QuestionAnalysisPanel } from "./QuestionAnalysisPanel";
import { QuestionTimeline } from "./QuestionTimeline";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { AnalysisReport, InterviewRetrospective } from "./retrospectiveTypes";

export function RetrospectiveWorkspace({ retrospective, report, selectedQuestionId, busy, onSelectQuestion, onStop, onResume, onRetry, onDecision }: {
  retrospective: InterviewRetrospective;
  report: AnalysisReport;
  selectedQuestionId: string | null;
  busy: boolean;
  onSelectQuestion: (id: string) => void;
  onStop: () => void;
  onResume: () => void;
  onRetry: () => void;
  onDecision: (decision: "confirmed" | "rejected") => void;
}) {
  const question = report.questions.find((item) => item.id === selectedQuestionId) ?? report.questions[0] ?? null;
  const analysis = report.analyses.find((item) => item.questionUnitId === question?.id) ?? null;
  const item = report.items.find((candidate) => candidate.questionUnitId === question?.id) ?? null;
  const returnTo = `/retrospectives?retrospectiveId=${encodeURIComponent(retrospective.id)}${question ? `&questionId=${encodeURIComponent(question.id)}` : ""}`;
  return <div className="retrospective-workbench">
    <header className="retrospective-workbench__header"><div><p>{retrospective.roundLabel}</p><h2>{retrospective.title}</h2></div><span>{report.analysisRun.status === "completed" ? "分析完成" : "渐进分析"}</span></header>
    <AnalysisProgress run={report.analysisRun} busy={busy} onStop={onStop} onResume={onResume} onRetry={onRetry} />
    <TaskWorkspace className="retrospective-workbench__workspace" labelledBy="retrospective-question-list-title">
      <TaskWorkspacePane className="retrospective-workbench__timeline" aria-label="面试问题列表">
        <QuestionTimeline questions={report.questions} analyses={report.analyses} items={report.items} selectedId={question?.id ?? null} onSelect={onSelectQuestion} />
      </TaskWorkspacePane>
      <TaskWorkspacePane className="retrospective-workbench__analysis" aria-label="问题分析详情">
        <QuestionAnalysisPanel question={question} analysis={analysis} item={item} executionId={report.analysisRun.executionId} returnTo={returnTo} busy={busy} onDecision={onDecision} />
      </TaskWorkspacePane>
    </TaskWorkspace>
  </div>;
}
