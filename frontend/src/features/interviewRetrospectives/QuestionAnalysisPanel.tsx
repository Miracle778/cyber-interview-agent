import { AlertTriangle, ArrowUpRight, CheckCircle2, FileQuestion, Lightbulb, ShieldAlert, Sparkles, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { AnalysisPoint, AnalysisWorkItem, InterviewQuestion, QuestionAnalysis } from "./retrospectiveTypes";
import { questionViewState, verdictLabel } from "./QuestionTimeline";

const GAP_LABELS: Record<string, string> = { knowledge: "知识差距", depth: "深度差距", expression: "表达差距", evidence: "证据差距" };
const EVIDENCE_LABELS: Record<string, string> = { direct: "直接来自原始回答", mixed: "结合原始回答与模型判断", model_judgment: "模型判断，建议核对" };

function PointList({ title, items, tone }: { title: string; items: AnalysisPoint[]; tone: string }) {
  if (!items.length) return null;
  return <section className="question-analysis__section" data-tone={tone}><h3>{title}</h3><ul>{items.map((item, index) => <li key={`${item.summary}-${index}`}>{item.summary}{item.evidenceSegmentIds.length ? <small>对应原文 {item.evidenceSegmentIds.length} 处</small> : null}</li>)}</ul></section>;
}

export function QuestionAnalysisPanel({ question, analysis, item, executionId, returnTo, busy, onDecision }: {
  question: InterviewQuestion | null;
  analysis: QuestionAnalysis | null;
  item: AnalysisWorkItem | null;
  executionId: string | null;
  returnTo: string;
  busy: boolean;
  onDecision: (decision: "confirmed" | "rejected") => void;
}) {
  if (!question) return <div className="question-analysis__empty"><FileQuestion size={28} /><h2>选择一道问题</h2><p>已完成的问题会边分析边出现在左侧。</p></div>;
  const state = questionViewState(question, analysis ?? undefined, item ?? undefined);
  const traceHref = executionId ? `/agents/executions/${encodeURIComponent(executionId)}?returnTo=${encodeURIComponent(returnTo)}` : null;
  return <article className="question-analysis" data-state={state}>
    <header className="question-analysis__header">
      <div><p>第 {question.ordinal} 题 · {question.origin === "inferred" ? "推断问题" : "面试原题"}</p><h2>{question.questionText}</h2></div>
      {analysis ? <span data-verdict={analysis.verdict}>{verdictLabel(analysis.verdict)}</span> : null}
    </header>

    {state === "failed" ? <div className="question-analysis__notice" data-tone="danger"><AlertTriangle size={20} /><div><strong>这道题分析失败</strong><p>已经完成的其他题目不受影响。可在上方重试，或打开运行详情查看原因。</p></div></div> : null}
    {question.origin === "inferred" && question.decisionStatus === "pending" ? <div className="question-analysis__notice" data-tone="warning"><Sparkles size={20} /><div><strong>这是一道推断题，请先确认</strong><p>{question.inferenceBasis || "系统根据上下文判断这里可能包含一道追问。"}</p><div><Button size="sm" onClick={() => onDecision("confirmed")} disabled={busy}><CheckCircle2 size={15} /> 确认是面试题</Button><Button size="sm" variant="secondary" onClick={() => onDecision("rejected")} disabled={busy}><X size={15} /> 不是面试题</Button></div></div></div> : null}

    {analysis ? <>
      <div className="question-analysis__meta"><span>{EVIDENCE_LABELS[analysis.evidenceLevel] ?? "证据来源待核对"}</span><span>结论置信度 {Math.round(analysis.confidence * 100)}%</span></div>
      {!analysis.sourceAvailable ? <div className="question-analysis__source-cleared"><ShieldAlert size={18} /><span>原始文字已清除，当前仅保留分析结论</span></div> : analysis.sourceExcerpt ? <blockquote><span>回答原文</span>{analysis.sourceExcerpt}</blockquote> : null}
      <div className="question-analysis__content">
        <PointList title="做得好的地方" items={analysis.strengths} tone="success" />
        <PointList title="可以提升" items={analysis.improvements} tone="warning" />
        <PointList title="遗漏内容" items={analysis.omissions} tone="danger" />
        {analysis.gaps.length ? <section className="question-analysis__section" data-tone="warning"><h3>能力差距</h3><ul>{analysis.gaps.map((gap, index) => <li key={`${gap.kind}-${index}`}><strong>{GAP_LABELS[gap.kind] ?? "待改进"}</strong>{gap.summary}</li>)}</ul></section> : null}
        {analysis.improvementOutline.length ? <section className="question-analysis__section"><h3>更好的回答结构</h3><ol>{analysis.improvementOutline.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></section> : null}
        {analysis.suggestedAnswer ? <section className="question-analysis__suggested"><h3><Lightbulb size={17} /> 参考表达</h3><p>{analysis.suggestedAnswer}</p></section> : null}
      </div>
    </> : state !== "failed" ? <div className="question-analysis__pending"><span /><h3>这道题还在分析</h3><p>你可以先查看左侧已经完成的问题。</p></div> : null}

    {traceHref ? <footer><Link to={traceHref} state={{ from: returnTo }}>查看高级运行详情 <ArrowUpRight size={16} /></Link></footer> : null}
  </article>;
}
