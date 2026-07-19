import { Archive, ArrowRight, FileStack, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { CurationSession, QuestionCandidate } from "./reviewTypes";

const stageMeta: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "neutral" }, reading_sources: { label: "读取资料", tone: "primary" }, generating: { label: "生成候选", tone: "primary" }, merging: { label: "合并去重", tone: "primary" }, summarizing: { label: "生成总结", tone: "primary" }, waiting_for_command: { label: "待确认", tone: "warning" }, publishing: { label: "发布中", tone: "primary" }, completed: { label: "已完成", tone: "success" }, failed: { label: "失败", tone: "danger" },
};

export function CurationSessionList({ sessions, candidateCount, publishedCount, onSelect, onCreate, onDelete, onOpenLibrary }: { sessions: CurationSession[]; candidateCount: number; publishedCount: number; onSelect: (id: string) => void; onCreate: () => void; onDelete: (id: string, hard: boolean) => void; onOpenLibrary: (status: QuestionCandidate["status"] | null) => void }) {
  const [onlyActive, setOnlyActive] = useState(false);
  const active = sessions.filter((session) => !["completed", "failed"].includes(session.stage));
  const ordered = [...active, ...sessions.filter((session) => !active.includes(session))];
  const visibleSessions = onlyActive ? active : ordered;
  return <main className="curation-landing">
    <header><div><span>题库 Agent</span><h2>整理会话</h2><p>回到正在进行的资料整理，或选择一组文件开启新的 Agent 会话。</p></div><Button onClick={onCreate}><Plus size={16} />新建整理会话</Button></header>
    <section className="curation-landing__summary" aria-label="整理会话概览">
      <button type="button" aria-pressed={onlyActive} title="包含排队、整理中、待确认和发布中的会话" onClick={() => setOnlyActive((current) => !current)}><strong>{active.length}</strong><span>待处理会话</span><small>{onlyActive ? "显示全部" : "查看会话"}<ArrowRight size={14} /></small></button>
      <button type="button" onClick={() => onOpenLibrary(null)}><strong>{candidateCount}</strong><span>累计候选</span><small>查看全部题目<ArrowRight size={14} /></small></button>
      <button type="button" onClick={() => onOpenLibrary("published")}><strong>{publishedCount}</strong><span>已发布</span><small>查看已发布题目<ArrowRight size={14} /></small></button>
    </section>
    {onlyActive ? <div className="curation-landing__filter"><span>仅显示待处理会话</span><button type="button" onClick={() => setOnlyActive(false)}>清除筛选</button></div> : null}
    <section className="curation-landing__list" aria-label="历史整理会话">
      {visibleSessions.length === 0 ? <div className="curation-landing__empty"><FileStack size={28} /><h3>{onlyActive ? "没有待处理会话" : "还没有整理会话"}</h3><p>{onlyActive ? "当前会话均已完成或失败，可清除筛选查看历史记录。" : "选择一份或多份原材料，题匠会保留完整过程、候选总结和确认记录。"}</p>{onlyActive ? <Button variant="secondary" onClick={() => setOnlyActive(false)}>查看全部会话</Button> : <Button onClick={onCreate}><Plus size={16} />创建第一个会话</Button>}</div> : visibleSessions.map((session) => {
        const meta = stageMeta[session.stage] ?? { label: session.stage, tone: "neutral" };
        return <article key={session.id} className="curation-landing__item">
          <button type="button" className="curation-landing__open" title={session.title} onClick={() => onSelect(session.id)}><div><strong>{session.title}</strong><small>{session.sources.map((source) => source.filename).join(" · ")}</small></div><span className={`badge badge--${meta.tone}`}>{meta.label}</span><p>{session.sources.length} 份资料 · {session.candidateCount} 道候选 · {session.pendingCount} 道待确认</p><ArrowRight size={18} /></button>
          <button type="button" className="curation-landing__delete" aria-label="归档当前会话" title={`归档 ${session.title}`} onClick={() => onDelete(session.id, false)}><Archive size={16} /></button>
        </article>;
      })}
    </section>
  </main>;
}
