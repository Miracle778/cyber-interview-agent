import { FileText, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { KnowledgeSource } from "../knowledge/knowledgeTypes";
import { Button } from "../../shared/ui/Button";

type SourceState = "not_curated" | "in_progress" | "previously_curated";

export function SourceSelectionDialog({ open, sources, sourceStates, busy, onClose, onConfirm }: { open: boolean; sources: KnowledgeSource[]; sourceStates: Record<string, SourceState>; busy: boolean; onClose: () => void; onConfirm: (ids: string[]) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    setSelected([]);
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    globalThis.addEventListener("keydown", closeOnEscape);
    return () => globalThis.removeEventListener("keydown", closeOnEscape);
  }, [open]);
  if (!open) return null;
  const selectedStates = selected.map((id) => sourceStates[id]);
  const hasPrevious = selectedStates.includes("previously_curated");
  const hasActive = selectedStates.includes("in_progress");
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="source-selection-dialog" role="dialog" aria-modal="true" aria-labelledby="source-selection-title">
        <header><div><h3 id="source-selection-title">选择整理资料</h3><p>所选文件共同形成一个可恢复的 Agent 会话。</p></div><button type="button" aria-label="关闭" onClick={onClose}><X size={18} /></button></header>
        <div className="source-selection-dialog__list">
          {sources.length === 0 ? <p className="status-note">还没有资料，请先导入文档。</p> : sources.map((source) => {
            const state = sourceStates[source.id] ?? "not_curated";
            const stateText = state === "in_progress" ? "正在整理" : state === "previously_curated" ? "整理过" : "未整理";
            return <label key={source.id}><input type="checkbox" checked={selected.includes(source.id)} onChange={() => setSelected((current) => current.includes(source.id) ? current.filter((id) => id !== source.id) : [...current, source.id])} /><FileText size={17} /><span><strong>{source.originalFilename}</strong><small>{Math.max(1, Math.ceil(source.sizeBytes / 1024))} KB</small></span><em data-state={state}>{stateText}</em></label>;
          })}
        </div>
        {hasPrevious ? <p className="source-selection-dialog__warning">这份资料之前整理过，仍可再次整理并自动合并相似题。</p> : null}
        {hasActive ? <p className="source-selection-dialog__warning">这份资料正在其他会话整理，仍可继续；新会话会独立保留过程。</p> : null}
        <footer><span>已选 {selected.length} 份</span><div className="btn-row"><Button variant="ghost" onClick={onClose}>取消</Button><Button disabled={selected.length === 0 || busy} loading={busy} onClick={() => onConfirm(selected)}>开始整理</Button></div></footer>
      </section>
    </div>
  );
}
