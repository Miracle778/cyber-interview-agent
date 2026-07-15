import { ArrowRight, FileStack, Plus, Trash2 } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { CurationSession } from "./reviewTypes";

const stageMeta: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "neutral" }, reading_sources: { label: "读取资料", tone: "primary" }, generating: { label: "生成候选", tone: "primary" }, merging: { label: "合并去重", tone: "primary" }, summarizing: { label: "生成总结", tone: "primary" }, waiting_for_command: { label: "待确认", tone: "warning" }, publishing: { label: "发布中", tone: "primary" }, completed: { label: "已完成", tone: "success" }, failed: { label: "失败", tone: "danger" },
};

export function CurationSessionList({ sessions, onSelect, onCreate, onDelete }: { sessions: CurationSession[]; onSelect: (id: string) => void; onCreate: () => void; onDelete: (id: string, hard: boolean) => void }) {
  const active = sessions.filter((session) => !["completed", "failed"].includes(session.stage));
  const ordered = [...active, ...sessions.filter((session) => !active.includes(session))];
  return <main className="curation-landing">
    <header><div><span>题库 Agent</span><h2>整理会话</h2><p>回到正在进行的资料整理，或选择一组文件开启新的 Agent 会话。</p></div><Button onClick={onCreate}><Plus size={16} />新建整理会话</Button></header>
    <section className="curation-landing__summary" aria-label="整理会话概览"><div><strong>{active.length}</strong><span>进行中</span></div><div><strong>{sessions.reduce((sum, item) => sum + item.candidateCount, 0)}</strong><span>累计候选</span></div><div><strong>{sessions.reduce((sum, item) => sum + item.publishedCount, 0)}</strong><span>已发布</span></div></section>
    <section className="curation-landing__list" aria-label="历史整理会话">
      {ordered.length === 0 ? <div className="curation-landing__empty"><FileStack size={28} /><h3>还没有整理会话</h3><p>选择一份或多份原材料，题匠会保留完整过程、候选总结和确认记录。</p><Button onClick={onCreate}><Plus size={16} />创建第一个会话</Button></div> : ordered.map((session) => {
        const meta = stageMeta[session.stage] ?? { label: session.stage, tone: "neutral" };
        return <article key={session.id} className="curation-landing__item">
          <button type="button" className="curation-landing__open" title={session.title} onClick={() => onSelect(session.id)}><div><strong>{session.title}</strong><small>{session.sources.map((source) => source.filename).join(" · ")}</small></div><span className={`badge badge--${meta.tone}`}>{meta.label}</span><p>{session.sources.length} 份资料 · {session.candidateCount} 道候选 · {session.pendingCount} 道待确认</p><ArrowRight size={18} /></button>
          <button type="button" className="curation-landing__delete" aria-label="删除当前会话" title={`删除 ${session.title}；按住 Shift 永久删除`} onClick={(event) => onDelete(session.id, event.shiftKey)}><Trash2 size={16} /></button>
        </article>;
      })}
    </section>
  </main>;
}
