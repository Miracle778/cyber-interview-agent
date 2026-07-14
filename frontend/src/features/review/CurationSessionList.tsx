import { FileStack, Plus } from "lucide-react";
import type { CurationSession } from "./reviewTypes";

function stageText(stage: CurationSession["stage"]) {
  if (stage === "waiting_for_command") return "待确认";
  if (stage === "completed") return "已完成";
  if (stage === "failed") return "失败";
  return "整理中";
}

export function CurationSessionList({ sessions, selectedId, onSelect, onCreate }: { sessions: CurationSession[]; selectedId: string | null; onSelect: (id: string) => void; onCreate: () => void }) {
  return (
    <aside className="curation-session-list" aria-label="整理会话列表">
      <div className="review-pane-title"><FileStack size={17} /><strong>按资料整理</strong><span>{sessions.length}</span></div>
      <button type="button" className="curation-session-list__new" onClick={onCreate}><Plus size={16} />新建整理会话</button>
      {sessions.length === 0 ? <p className="status-note">暂无整理会话。选择资料后让 Agent 开始整理。</p> : null}
      {sessions.map((session) => (
        <button type="button" key={session.id} className="review-history__item" aria-current={session.id === selectedId} onClick={() => onSelect(session.id)}>
          <strong>{session.title}</strong>
          <span>{session.sources.length} 份资料 · {session.candidateCount} 道题</span>
          <small>{stageText(session.stage)} · 待确认 {session.pendingCount}</small>
        </button>
      ))}
    </aside>
  );
}
