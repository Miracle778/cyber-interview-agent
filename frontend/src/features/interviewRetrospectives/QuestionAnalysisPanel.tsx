import { AlertTriangle, ArrowUpRight, CheckCircle2, ChevronDown, FileQuestion, Lightbulb, ShieldAlert, Sparkles, Target, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { AnalysisPoint, AnalysisWorkItem, InterviewQuestion, QuestionAnalysis } from "./retrospectiveTypes";
import { questionViewState, verdictLabel } from "./QuestionTimeline";

const GAP_LABELS: Record<string, string> = { knowledge: "知识差距", depth: "深度差距", expression: "表达差距", evidence: "证据差距" };
const EVIDENCE_LABELS: Record<string, string> = { direct: "直接来自原始回答", mixed: "结合原始回答与模型判断", model_judgment: "模型判断，建议核对" };

export function humanizeInferenceBasis(value: string) {
  if (!value) return "系统根据上下文判断这里可能包含一道追问。";
  return value
    .replace(/recordingCoverage\s*=\s*candidate_only\s*[；;,，]?\s*/gi, "这份录音主要保留了候选人的回答；")
    .replace(/recordingCoverage\s*=\s*full_dialogue\s*[；;,，]?\s*/gi, "这份录音包含双方对话；")
    .replace(/speakerHints\s*=\s*[^；;,，]+\s*[；;,，]?\s*/gi, "")
    .replace(/candidate_only/gi, "仅录到候选人")
    .trim();
}

function PointList({ title, items, tone }: { title: string; items: AnalysisPoint[]; tone: string }) {
  if (!items.length) return null;
  return <section className="question-analysis__section" data-tone={tone}><h3>{title}</h3><ul>{items.map((item, index) => <li key={`${item.summary}-${index}`}>{item.summary}{item.evidenceSegmentIds.length ? <small>对应原文 {item.evidenceSegmentIds.length} 处</small> : null}</li>)}</ul></section>;
}

function KeyConclusion({ label, text, tone }: { label: string; text: string; tone: "success" | "warning" }) {
  return <section className="question-analysis__key" data-tone={tone}><span>{label}</span><p>{text}</p></section>;
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
    {question.origin === "inferred" && question.decisionStatus === "pending" ? <div className="question-analysis__notice" data-tone="warning"><Sparkles size={20} /><div><strong>这是一道推断题，请先确认</strong><p>{humanizeInferenceBasis(question.inferenceBasis)}</p><div><Button size="sm" onClick={() => onDecision("confirmed")} disabled={busy}><CheckCircle2 size={15} /> 确认是面试题</Button><Button size="sm" variant="secondary" onClick={() => onDecision("rejected")} disabled={busy}><X size={15} /> 不是面试题</Button></div></div></div> : null}

    {analysis ? <>
      <div className="question-analysis__meta"><span>{EVIDENCE_LABELS[analysis.evidenceLevel] ?? "证据来源待核对"}</span><span>结论置信度 {Math.round(analysis.confidence * 100)}%</span></div>
      <section className="question-analysis__overview" aria-labelledby="question-analysis-overview-title">
        <div className="question-analysis__overview-title"><Target size={18} /><div><p>本题结论</p><h3 id="question-analysis-overview-title">先抓住最重要的两件事</h3></div></div>
        <div className="question-analysis__keys">
          <KeyConclusion label="值得保留" text={analysis.strengths[0]?.summary ?? "当前回答还没有识别出明确优势。"} tone="success" />
          <KeyConclusion label="优先改进" text={analysis.improvements[0]?.summary ?? analysis.omissions[0]?.summary ?? analysis.gaps[0]?.summary ?? "当前回答没有高优先级问题。"} tone="warning" />
        </div>
      </section>

      {analysis.improvementOutline.length ? <section className="question-analysis__plan"><header><Lightbulb size={18} /><div><p>推荐回答结构</p><h3>下一次按这个顺序回答</h3></div></header><ol>{analysis.improvementOutline.map((step, index) => <li key={`${step}-${index}`}><span>{index + 1}</span><p>{step}</p></li>)}</ol></section> : null}

      <div className="question-analysis__disclosures">
        {(analysis.strengths.length || analysis.improvements.length || analysis.omissions.length || analysis.gaps.length) ? <details><summary><span>查看完整分析</span><small>{analysis.strengths.length + analysis.improvements.length + analysis.omissions.length + analysis.gaps.length} 条结论</small><ChevronDown size={17} /></summary><div className="question-analysis__content">
          <PointList title="做得好的地方" items={analysis.strengths} tone="success" />
          <PointList title="可以提升" items={analysis.improvements} tone="warning" />
          <PointList title="遗漏内容" items={analysis.omissions} tone="danger" />
          {analysis.gaps.length ? <section className="question-analysis__section" data-tone="warning"><h3>能力差距</h3><ul>{analysis.gaps.map((gap, index) => <li key={`${gap.kind}-${index}`}><strong>{GAP_LABELS[gap.kind] ?? "待改进"}</strong>{gap.summary}</li>)}</ul></section> : null}
        </div></details> : null}
        {!analysis.sourceAvailable ? <div className="question-analysis__source-cleared"><ShieldAlert size={18} /><span>原始文字已清除，当前仅保留分析结论</span></div> : analysis.sourceExcerpt ? <details><summary><span>查看回答原文</span><small>{analysis.sourceExcerpt.length.toLocaleString()} 字</small><ChevronDown size={17} /></summary><blockquote><span>回答原文</span>{analysis.sourceExcerpt}</blockquote></details> : null}
        {analysis.suggestedAnswer ? <details><summary><span>查看参考表达</span><small>根据本题结论生成</small><ChevronDown size={17} /></summary><section className="question-analysis__suggested"><h3><Lightbulb size={17} /> 参考表达</h3><p>{analysis.suggestedAnswer}</p></section></details> : null}
      </div>
    </> : state !== "failed" ? <div className="question-analysis__pending"><span /><h3>这道题还在分析</h3><p>你可以先查看左侧已经完成的问题。</p></div> : null}

    {traceHref ? <footer><Link to={traceHref} state={{ from: returnTo }}>查看高级运行详情 <ArrowUpRight size={16} /></Link></footer> : null}
  </article>;
}
