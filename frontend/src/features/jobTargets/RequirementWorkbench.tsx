import { useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { JobRequirement } from "./jobTargetTypes";

export function RequirementWorkbench({ requirements, busy = false, onDecide }: { requirements: JobRequirement[]; busy?: boolean; onDecide: (ids: string[], decision: "confirmed" | "rejected") => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const safe = useMemo(() => requirements.filter((item) => item.confirmationStatus === "pending" && !item.inferred && Boolean(item.sourceQuote)), [requirements]);
  const inferred = requirements.filter((item) => item.confirmationStatus === "pending" && item.inferred).length;
  const active = requirements.find((item) => item.id === selected[0]) ?? requirements[0];
  function toggle(id: string) { setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  return <section className="requirement-workbench">
    <header><div><h2>岗位要求</h2><p>先确认原文明确写出的要求；推断内容需要逐条核对。</p></div><Button variant="secondary" onClick={() => setSelected(safe.map((item) => item.id))}>选择可安全确认项</Button></header>
    {inferred ? <p className="requirement-workbench__notice">{inferred} 条推断建议需要单独核对</p> : null}
    <div className="requirement-workbench__body">
      <div className="requirement-workbench__queue" aria-label="岗位要求列表">
        {requirements.map((item) => <label key={item.id} className={active?.id === item.id ? "is-active" : ""}>
          <input type="checkbox" aria-label={item.text} checked={selected.includes(item.id)} disabled={item.confirmationStatus !== "pending"} onChange={() => toggle(item.id)} />
          <span><strong>{item.text}</strong><small>{item.inferred ? "系统推断，需单独核对" : item.sourceQuote || "未找到直接原文"}</small></span>
          <em>{item.confirmationStatus === "pending" ? "待确认" : item.confirmationStatus === "confirmed" ? "已确认" : "已忽略"}</em>
        </label>)}
      </div>
      <article className="requirement-workbench__detail">
        {active ? <><span>{active.priority === "must_have" ? "核心要求" : "加分项"}</span><h3>{active.text}</h3><h4>岗位原文</h4><blockquote>{active.sourceQuote || "这是系统根据上下文推断的内容，没有直接原文。"}</blockquote><h4>当前准备情况</h4><p>{active.preparationStatus === "reliable_evidence" ? "已有可靠经历支持" : "建议通过项目深挖补充证据和表达"}</p></> : <p>暂无岗位要求。</p>}
      </article>
    </div>
    <footer><span>已选 {selected.length} 条，可安全确认 {safe.length} 条，需单独核对 {inferred} 条</span><div><Button variant="secondary" disabled={!selected.length || busy} onClick={() => onDecide(selected, "rejected")}>忽略所选</Button><Button disabled={!selected.length || busy} onClick={() => onDecide(selected, "confirmed")}>确认所选</Button></div></footer>
  </section>;
}
