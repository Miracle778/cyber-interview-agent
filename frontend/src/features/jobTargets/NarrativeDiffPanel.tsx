import { useState } from "react";
import { Button } from "../../shared/ui/Button";

export interface NarrativeChange { id: string; section: string; current: string; suggested: string }

export function NarrativeDiffPanel({ changes, onConfirm }: { changes: NarrativeChange[]; onConfirm: (ids: string[], edits: Record<string, string>) => void }) {
  const [selected, setSelected] = useState(changes.map((item) => item.id));
  const [edits, setEdits] = useState<Record<string, string>>({});
  return <section className="narrative-diff"><header><h3>项目讲解建议</h3><p>只会更新你勾选并确认的段落。</p></header>{changes.map((item) => <article key={item.id}><label><input type="checkbox" checked={selected.includes(item.id)} onChange={() => setSelected((ids) => ids.includes(item.id) ? ids.filter((id) => id !== item.id) : [...ids, item.id])} />{item.section}</label><div><p><small>当前内容</small>{item.current || "暂无"}</p><label><small>建议内容</small><textarea value={edits[item.id] ?? item.suggested} onChange={(event) => setEdits((value) => ({ ...value, [item.id]: event.target.value }))} /></label></div></article>)}<footer><span>已选 {selected.length} 个段落</span><Button disabled={!selected.length} onClick={() => onConfirm(selected, edits)}>确认所选段落</Button></footer></section>;
}
