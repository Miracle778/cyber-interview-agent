import { AlertTriangle, Bot, CheckCircle2, Code2, Eye, FileText, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { formatBeijingDateTime } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { MarkdownView } from "../knowledge/MarkdownView";
import type { QuestionCandidate } from "./reviewTypes";
import { uniqueSourceCount } from "./sourceReferences";

const statusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已入库",
  rejected: "待修改",
};

const difficultyLabels: Record<QuestionCandidate["question"]["difficulty"], string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

function markdownSection(markdown: string, heading: string) {
  const parts = markdown.split(/^##\s+(.+)\s*$/gm);
  for (let index = 1; index < parts.length; index += 2) {
    if (parts[index].trim() === heading) return parts[index + 1]?.trim();
  }
  return undefined;
}

function markdownList(markdown: string, heading: string) {
  return markdownSection(markdown, heading)
    ?.split("\n")
    .map((line) => line.replace(/^\s*[-*+]\s+/, "").trim())
    .filter((line) => Boolean(line) && line !== "暂无");
}

function candidateMarkdown(candidate: QuestionCandidate) {
  const required = candidate.question.requiredKeyPoints ?? candidate.question.keyPoints;
  const bonus = candidate.question.bonusKeyPoints ?? [];
  return `# ${candidate.question.title}\n\n## 题目\n\n${candidate.question.questionText}\n\n## 参考答案\n\n${candidate.question.referenceAnswer}\n\n## 必答点\n\n${required.map((point) => `- ${point}`).join("\n")}\n\n## 加分点\n\n${bonus.length ? bonus.map((point) => `- ${point}`).join("\n") : "- 暂无"}`;
}

type QuestionSaveValues = {
  version: number;
  title: string;
  questionText: string;
  referenceAnswer: string;
  keyPoints: string[];
  requiredKeyPoints: string[];
  bonusKeyPoints: string[];
};

export function QuestionDetailPanel({ candidate, sourceLabels, busy, approvalPending = false, publicationBlockedReason, onSave, onRewrite, onConfirm, onPublish, onDelete, onOpenSession }: { candidate: QuestionCandidate | null; sourceLabels: Record<string, string>; busy: boolean; approvalPending?: boolean; publicationBlockedReason?: string; onSave: (values: QuestionSaveValues) => void; onRewrite: (feedback: string) => void; onConfirm: () => void; onPublish?: () => void; onDelete?: () => void; onOpenSession: (candidateId: string) => void }) {
  const [mode, setMode] = useState<"preview" | "source">("preview");
  const [feedback, setFeedback] = useState(candidate?.rejectionReason ?? "");
  const [source, setSource] = useState(candidate?.draft?.markdown ?? (candidate ? candidateMarkdown(candidate) : ""));
  if (!candidate) return <div className="question-detail-empty"><Eye size={22} /><p>选择一道候选题查看详情</p></div>;
  const draft = candidate.draft;
  const markdown = (draft?.markdown ?? candidateMarkdown(candidate)).replace(/^# [^\n]+\n+/, "");
  const saveSource = () => {
    const title = source.match(/^#\s+(.+)$/m)?.[1].trim() || candidate.question.title;
    const questionText = markdownSection(source, "题目") || candidate.question.questionText;
    const referenceAnswer = markdownSection(source, "参考答案") || candidate.question.referenceAnswer;
    const requiredKeyPoints = markdownList(source, "必答点")
      ?? markdownList(source, "关键点")
      ?? candidate.question.requiredKeyPoints
      ?? candidate.question.keyPoints;
    const bonusKeyPoints = markdownList(source, "加分点")
      ?? candidate.question.bonusKeyPoints
      ?? [];
    const keyPoints = [...new Set([...requiredKeyPoints, ...bonusKeyPoints])];
    onSave({ version: draft?.version ?? 1, title, questionText, referenceAnswer, keyPoints, requiredKeyPoints, bonusKeyPoints });
  };
  return (
    <section className="question-detail" aria-label="题目详情" key={candidate.id}>
      <div className="question-detail__scroll">
        <header className="question-detail__header">
          <div className="question-detail__breadcrumb">{candidate.question.topics.join(" / ") || "未分类"}</div>
          <h3>{candidate.question.title}</h3>
          <div className="question-detail__meta"><span className={`question-library__badge question-library__badge--${candidate.status}`}>{statusLabels[candidate.status]}</span><span>难度：{difficultyLabels[candidate.question.difficulty]}</span><span>来源：{uniqueSourceCount(candidate.sourceRefs)} 份资料</span></div>
        </header>
        <div className="segmented-control" aria-label="详情显示模式"><button aria-pressed={mode === "preview"} onClick={() => setMode("preview")}><Eye size={14} />阅读</button><button aria-pressed={mode === "source"} onClick={() => setMode("source")}><Code2 size={14} />原文</button></div>
        <div className="question-detail__content">
          {mode === "preview" ? <MarkdownView markdown={markdown} /> : null}
          {mode === "source" ? <div className="question-source-editor"><label className="field"><span className="field__label">Markdown 原文</span><textarea className="field__input question-source-editor__input" aria-label="Markdown 原文" value={source} onChange={(event) => setSource(event.target.value)} /></label><Button loading={busy} onClick={saveSource}>保存修改</Button></div> : null}
        </div>
        <section className="source-evidence" aria-label="来源证据"><div><FileText size={16} /><strong>来源证据</strong><span>{candidate.sourceRefs.length}</span></div><ul>{candidate.sourceRefs.map((ref) => { const sourceId = Object.keys(sourceLabels).find((id) => ref === id || ref.startsWith(`${id}#`)); return <li key={ref}>{sourceId ? sourceLabels[sourceId] : ref}{ref.includes("#") ? ` · ${ref.slice(ref.indexOf("#") + 1)}` : ""}</li>; })}</ul></section>
        {(candidate.needsReview || candidate.answerBasis !== "source" || candidate.materialSupport !== "sufficient") ? <aside className="candidate-quality-warning" role="note"><AlertTriangle size={18} /><div><strong>{["model", "unknown"].includes(candidate.answerBasis ?? "unknown") ? "主要由 AI 生成" : candidate.answerBasis === "mixed" ? "答案含 AI 补全" : "材料依据需要复核"}</strong><p>{candidate.materialSupport === "partial" ? "原资料只能部分支撑答案。" : candidate.materialSupport === "minimal" ? "原资料提供的支撑很少。" : candidate.materialSupport === "sufficient" ? "材料支撑充分，但仍标记为需要复核。" : "材料支撑程度尚未确认。"} 发布时会要求你明确确认这项风险。</p>{(candidate.normalizationIssues?.length ?? 0) > 0 ? <small>整理过程中做过安全修复，请重点核对题目和答案。</small> : null}</div></aside> : null}
        {candidate.status === "rejected" ? <aside className="candidate-rejection" role="note"><AlertTriangle size={18} /><div><strong>退回修改原因</strong><p>{candidate.rejectionReason || "未记录退回原因"}</p>{candidate.rejectedAt ? <small>{formatBeijingDateTime(candidate.rejectedAt) ?? candidate.rejectedAt}</small> : null}</div></aside> : null}
        <aside className="ai-suggestion"><Bot size={18} /><div><strong>AI 整理建议</strong><p>{candidate.correctionNote || "题目结构完整，建议核对参考答案后入库。"}</p></div></aside>
        {candidate.duplicateOfQuestionId ? <aside className="duplicate-warning"><AlertTriangle size={18} /><div><strong>发现相似已发布题目</strong>{candidate.duplicateQuestion ? <><p><b>{candidate.duplicateQuestion.title}</b></p><p>{candidate.duplicateQuestion.questionText}</p></> : <p>题目 ID：{candidate.duplicateOfQuestionId}</p>}<small>确认前请比较题目与答案差异。</small></div></aside> : null}
        <div className="rewrite-row"><label className="field"><span className="field__label">{candidate.status === "rejected" ? "按退回原因让 AI 在原会话中重写" : "让 AI 重新整理"}</span><input className="field__input" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="例如：增加故障排查场景" /></label><Button variant="secondary" disabled={!feedback.trim() || busy} onClick={() => onRewrite(feedback.trim())}><RefreshCw size={15} />重新整理</Button><button type="button" className="text-link" onClick={() => onOpenSession(candidate.id)}>查看生成会话</button>{onDelete ? <Button variant="danger" disabled={busy} onClick={onDelete}><Trash2 size={15} />删除题目</Button> : null}</div>
      </div>
      {candidate.status === "review_pending" ? <section className="candidate-confirm"><CheckCircle2 size={18} /><div><strong>{publicationBlockedReason ? "已归入现有逻辑题目" : approvalPending ? "发布审批已发起" : candidate.confirmationStatus === "confirmed" ? "内容已确认，可以发布" : "先确认内容，再决定是否发布"}</strong><p>{publicationBlockedReason ?? (approvalPending ? "可通过页面右下角的待处理入口继续审批。" : candidate.confirmationStatus === "confirmed" ? "确认只代表内容审核通过；发布后才会进入可复习题库。" : "核对题目、答案和必答点。确认不会自动发布。")}</p></div>{!approvalPending && !publicationBlockedReason ? candidate.confirmationStatus === "confirmed" ? <Button loading={busy} onClick={onPublish}>发布入库</Button> : <Button loading={busy} onClick={onConfirm}>确认内容</Button> : null}</section> : null}
      {candidate.status === "rejected" ? <section className="candidate-confirm candidate-confirm--revision"><RefreshCw size={18} /><div><strong>修改后可重新提交审批</strong><p>可手动编辑原文，或按退回原因让 AI 在原整理会话中重写。</p></div><Button variant="secondary" disabled={busy} onClick={() => setMode("source")}>手动修改</Button></section> : null}
    </section>
  );
}
