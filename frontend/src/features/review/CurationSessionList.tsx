import { FileStack, Plus } from "lucide-react";
import type { CurationSession } from "./reviewTypes";

const stageMeta: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "neutral" },
  reading_sources: { label: "读取资料", tone: "primary" },
  generating: { label: "生成候选", tone: "primary" },
  merging: { label: "合并去重", tone: "primary" },
  summarizing: { label: "生成总结", tone: "primary" },
  waiting_for_command: { label: "待确认", tone: "warning" },
  publishing: { label: "发布中", tone: "primary" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

export function CurationSessionList({ sessions, selectedId, onSelect, onCreate }: { sessions: CurationSession[]; selectedId: string | null; onSelect: (id: string) => void; onCreate: () => void }) {
  return (
    <aside className="curation-session-list" aria-label="整理会话列表">
      <div className="review-pane-title"><FileStack size={17} /><strong>按资料整理</strong><span>{sessions.length}</span></div>
      <button type="button" className="curation-session-list__new" onClick={onCreate}><Plus size={16} />新建整理会话</button>
      {sessions.length === 0 ? <p className="status-note">暂无整理会话。选择资料后让题匠开始整理。</p> : null}
      <div className="curation-session-list__items">
        {sessions.map((session) => {
          const meta = stageMeta[session.stage] ?? { label: session.stage, tone: "neutral" };
          return (
            <button type="button" key={session.id} className="curation-session-item" aria-current={session.id === selectedId} onClick={() => onSelect(session.id)}>
              <div className="curation-session-item__head"><strong>{session.title}</strong><span className={`badge badge--${meta.tone}`}>{meta.label}</span></div>
              <div className="curation-session-item__meta"><span>{session.sources.length} 份资料</span><span>{session.candidateCount} 道题</span>{session.pendingCount > 0 ? <span className="curation-session-item__pending">待确认 {session.pendingCount}</span> : null}</div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
