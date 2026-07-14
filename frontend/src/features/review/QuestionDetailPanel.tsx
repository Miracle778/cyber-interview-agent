import { AlertTriangle, Bot, CheckCircle2, Code2, Eye, Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import { MarkdownView } from "../knowledge/MarkdownView";
import type { QuestionCandidate } from "./reviewTypes";

export function QuestionDetailPanel({ candidate, sourceLabels, busy, onSave, onRewrite, onConfirm }: { candidate: QuestionCandidate | null; sourceLabels: Record<string, string>; busy: boolean; onSave: (values: { version: number; title: string; questionText: string; referenceAnswer: string }) => void; onRewrite: (feedback: string) => void; onConfirm: () => void }) {
  const [mode, setMode] = useState<"preview" | "source" | "edit">("preview");
  const [feedback, setFeedback] = useState("");
  const [title, setTitle] = useState(candidate?.question.title ?? "");
  const [questionText, setQuestionText] = useState(candidate?.question.questionText ?? "");
  const [referenceAnswer, setReferenceAnswer] = useState(candidate?.question.referenceAnswer ?? "");
  if (!candidate) return <div className="question-detail-empty"><Eye size={22} /><p>选择一道候选题查看详情</p></div>;
  const draft = candidate.draft;
  return (
    <section className="question-detail" aria-label="题目详情" key={candidate.id}>
      <header className="question-detail__header"><div><span>{candidate.question.difficulty} · {candidate.question.topics.join(" / ")}</span><h3>{candidate.question.title}</h3></div><div className="segmented-control" aria-label="详情显示模式"><button aria-pressed={mode === "preview"} onClick={() => setMode("preview")}><Eye size={14} />渲染</button><button aria-pressed={mode === "source"} onClick={() => setMode("source")}><Code2 size={14} />Markdown 原文</button><button aria-pressed={mode === "edit"} onClick={() => setMode("edit")}><Pencil size={14} />编辑</button></div></header>
      {mode === "preview" ? <MarkdownView markdown={draft?.markdown ?? `# ${candidate.question.title}\n\n## 题目\n\n${candidate.question.questionText}\n\n## 参考答案\n\n${candidate.question.referenceAnswer}`} /> : null}
      {mode === "source" ? <pre className="report-preview">{draft?.markdown}</pre> : null}
      {mode === "edit" ? <div className="question-edit-form"><label className="field"><span className="field__label">标题</span><input className="field__input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="field"><span className="field__label">题目</span><textarea className="field__input field__input--area" value={questionText} onChange={(event) => setQuestionText(event.target.value)} /></label><label className="field"><span className="field__label">参考答案</span><textarea className="field__input field__input--area" value={referenceAnswer} onChange={(event) => setReferenceAnswer(event.target.value)} /></label><Button loading={busy} onClick={() => onSave({ version: draft?.version ?? 1, title, questionText, referenceAnswer })}>保存草稿</Button></div> : null}
      <section className="source-evidence" aria-label="来源证据"><strong>来源证据</strong><ul>{candidate.sourceRefs.map((ref) => { const sourceId = Object.keys(sourceLabels).find((id) => ref === id || ref.startsWith(`${id}#`)); return <li key={ref}>{sourceId ? sourceLabels[sourceId] : ref}{ref.includes("#") ? ` · ${ref.slice(ref.indexOf("#") + 1)}` : ""}</li>; })}</ul></section>
      <aside className="ai-suggestion"><Bot size={18} /><div><strong>AI 整理建议</strong><p>{candidate.correctionNote || "题目结构完整，建议核对参考答案后入库。"}</p></div></aside>
      {candidate.duplicateOfQuestionId ? <aside className="duplicate-warning"><AlertTriangle size={18} /><div><strong>发现相似已发布题目</strong>{candidate.duplicateQuestion ? <><p><b>{candidate.duplicateQuestion.title}</b></p><p>{candidate.duplicateQuestion.questionText}</p></> : <p>题目 ID：{candidate.duplicateOfQuestionId}</p>}<small>确认前请比较题目与答案差异。</small></div></aside> : null}
      <div className="rewrite-row"><label className="field"><span className="field__label">让 AI 重写</span><input className="field__input" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="例如：增加故障排查场景" /></label><Button variant="secondary" disabled={!feedback.trim() || busy} onClick={() => onRewrite(feedback.trim())}><RefreshCw size={15} />重新整理</Button></div>
      {candidate.status === "review_pending" ? <section className="candidate-confirm"><CheckCircle2 size={18} /><div><strong>需要人工确认</strong><p>确认后创建发布审批；批准之前不会进入可复习题库。</p></div><Button loading={busy} onClick={onConfirm}>确认入库</Button></section> : null}
    </section>
  );
}
