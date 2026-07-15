import { AlertTriangle, ArrowLeft, Bot, FileText } from "lucide-react";
import { MarkdownView } from "../knowledge/MarkdownView";
import type { QuestionCandidate } from "./reviewTypes";

export function CurationArtifactDetail({ candidate, onClose }: { candidate: QuestionCandidate; onClose: () => void }) {
  return <aside className="curation-artifact-detail" aria-label="Markdown 文件详情">
    <header><button type="button" onClick={onClose} aria-label="返回运行状态"><ArrowLeft size={16} />运行状态</button><span><FileText size={15} />Markdown 预览</span></header>
    <div className="curation-artifact-detail__body">
      <div className="curation-artifact-detail__title"><small>{candidate.question.difficulty} · {candidate.question.topics.join(" / ")}</small><h3>{candidate.question.title}</h3></div>
      <MarkdownView markdown={candidate.draft?.markdown ?? `# ${candidate.question.title}\n\n## 题目\n\n${candidate.question.questionText}\n\n## 参考答案\n\n${candidate.question.referenceAnswer}`} />
      <section className="curation-artifact-advice"><Bot size={18} /><div><strong>AI 整理建议</strong><p>{candidate.correctionNote || "题目结构完整，建议核对参考答案后发布。"}</p></div></section>
      {candidate.duplicateOfQuestionId ? <section className="curation-artifact-duplicate"><AlertTriangle size={18} /><div><strong>发现相似题目</strong>{candidate.duplicateQuestion ? <><p>{candidate.duplicateQuestion.title}</p><small>{candidate.duplicateQuestion.questionText}</small></> : <small>题目 ID：{candidate.duplicateOfQuestionId}</small>}</div></section> : null}
    </div>
  </aside>;
}
