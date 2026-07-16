import { Check, Eye, FileText, MessageSquareText, Send } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { QuestionCandidate } from "./reviewTypes";

const statusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已发布",
  rejected: "已拒绝",
};

const difficultyLabels: Record<QuestionCandidate["question"]["difficulty"], string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

interface CurationArtifactCardProps {
  candidate: QuestionCandidate;
  title?: string;
  description?: string;
  historical?: boolean;
  compact?: boolean;
  busy?: boolean;
  onOpen: (candidateId: string) => void;
  onPublish: (candidateId: string) => void;
  onSaveNote: (candidateId: string, note: string) => void;
}

export function CurationArtifactCard({ candidate, title, description, historical = false, compact = false, busy = false, onOpen, onPublish, onSaveNote }: CurationArtifactCardProps) {
  const [editingNote, setEditingNote] = useState(false);
  const [note, setNote] = useState(candidate.reviewNote);
  const published = candidate.status === "published";
  const filename = `${title ?? candidate.question.title}.md`;
  const metadata = description ?? `${candidate.question.topics.join(" / ") || "未分类"} · ${difficultyLabels[candidate.question.difficulty]}`;

  return <article className={`curation-artifact-card${compact ? " is-compact" : ""}${published ? " is-published" : ""}`}>
    <div className="curation-artifact-card__main">
      <span className="curation-artifacts__file" aria-hidden="true"><FileText size={16} /></span>
      <div className="curation-artifact-card__copy"><strong title={filename}>{filename}</strong><small>{metadata}{candidate.reviewNote ? " · 已备注" : ""}</small></div>
      <div className="curation-artifact-card__badges">{historical ? <span className="curation-artifact-card__history">历史版本</span> : null}<em className={`candidate-status candidate-status--${candidate.status}`}>{published ? <Check size={13} /> : null}{statusLabels[candidate.status]}</em></div>
    </div>
    {compact ? <p className="curation-artifact-card__excerpt">{candidate.question.questionText}</p> : null}
    <div className="curation-artifacts__actions">
      <button type="button" onClick={() => onOpen(candidate.id)}><Eye size={14} />查看</button>
      <button type="button" disabled={published || busy} onClick={() => onPublish(candidate.id)}><Send size={14} />{published ? "已发布" : "发布"}</button>
      <button type="button" aria-expanded={editingNote} onClick={() => { setNote(candidate.reviewNote); setEditingNote((value) => !value); }}><MessageSquareText size={14} />备注</button>
    </div>
    {editingNote ? <div className="curation-note-editor">
      <label htmlFor={`candidate-note-${candidate.id}`}>修改备注</label>
      <textarea id={`candidate-note-${candidate.id}`} autoFocus value={note} onChange={(event) => setNote(event.target.value)} placeholder="写下修改意见；保存后不会立即重新生成" />
      <small>保存备注只记录意见。稍后可在会话中让 Agent 按备注重新生成。</small>
      <div><button type="button" onClick={() => setEditingNote(false)}>取消</button><Button type="button" disabled={busy} loading={busy} onClick={() => { onSaveNote(candidate.id, note); setEditingNote(false); }}>保存备注</Button></div>
    </div> : null}
  </article>;
}
