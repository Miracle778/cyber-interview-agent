import { AlertTriangle, Check, CircleDashed, LoaderCircle, Sparkles } from "lucide-react";
import type { AnalysisWorkItem, InterviewQuestion, QuestionAnalysis } from "./retrospectiveTypes";

export type QuestionViewState = "failed" | "running" | "completed" | "pending";

export function questionViewState(question: InterviewQuestion, analysis: QuestionAnalysis | undefined, item: AnalysisWorkItem | undefined): QuestionViewState {
  if (["retryable", "blocked"].includes(item?.status ?? "") || item?.lastErrorCode) return "failed";
  if (item?.status === "running") return "running";
  if (analysis || item?.status === "completed") return "completed";
  return "pending";
}

const STATE_LABELS: Record<QuestionViewState, string> = { failed: "分析失败", running: "分析中", completed: "已完成", pending: "待分析" };

export function QuestionTimeline({ questions, analyses, items, selectedId, onSelect }: {
  questions: InterviewQuestion[];
  analyses: QuestionAnalysis[];
  items: AnalysisWorkItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const analysisByQuestion = new Map(analyses.map((item) => [item.questionUnitId, item]));
  const itemByQuestion = new Map(items.filter((item) => item.questionUnitId).map((item) => [item.questionUnitId!, item]));
  return <div className="question-timeline">
    <header><div><p>问题时间线</p><h2>本场问题</h2></div><span>{questions.filter((item) => item.decisionStatus !== "rejected" && item.decisionStatus !== "superseded").length} 题</span></header>
    <div className="question-timeline__items">
      {questions.filter((item) => item.decisionStatus !== "rejected" && item.decisionStatus !== "superseded").map((question) => {
        const analysis = analysisByQuestion.get(question.id);
        const state = questionViewState(question, analysis, itemByQuestion.get(question.id));
        const StateIcon = state === "failed" ? AlertTriangle : state === "running" ? LoaderCircle : state === "completed" ? Check : CircleDashed;
        const summaryLabel = analysis && state === "completed" ? verdictLabel(analysis.verdict) : STATE_LABELS[state];
        const pendingInference = question.origin === "inferred" && question.decisionStatus === "pending";
        return <button type="button" key={question.id} data-selected={selectedId === question.id} data-state={state} onClick={() => onSelect(question.id)}>
          <span className="question-timeline__ordinal">{question.ordinal}</span>
          <span className="question-timeline__copy"><strong>{question.questionText}</strong><small><span data-state={state}>{pendingInference ? <Sparkles size={13} /> : <StateIcon size={13} />} {pendingInference ? `需确认 · ${summaryLabel}` : summaryLabel}</span></small></span>
        </button>;
      })}
      {!questions.length ? <div className="question-timeline__empty"><CircleDashed size={24} /><p>正在识别面试问题，识别完成后会逐题显示。</p></div> : null}
    </div>
  </div>;
}

export function verdictLabel(verdict: string) {
  return ({ strong: "回答扎实", improvable: "可以提升", high_risk: "优先改进" } as Record<string, string>)[verdict] ?? "待评估";
}
