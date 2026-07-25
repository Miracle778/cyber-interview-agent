import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { JobRequirement } from "./jobTargetTypes";

type RequirementView = "pending" | "confirmed" | "rejected";

const backgroundCues = ["团队是", "团队为", "服务于", "致力于", "产品包括", "产品有", "全站", "最大的", "上线了", "对外输出", "技术团队", "基础中间件", "团队负责", "部门负责", "团队介绍", "部门介绍", "公司简介", "业务线", "产品线", "福利", "工作地点"];
const candidateCues = ["要求", "具备", "熟悉", "掌握", "精通", "了解", "学历", "经验", "能力", "优先", "负责", "主导", "参与", "能够", "需要"];
const heading = /^(公司简介|岗位介绍|职位介绍|团队介绍|部门介绍|任职资格|职位要求|岗位要求|优先(考虑)?条件|加分项|岗位职责|工作职责|福利待遇|工作地点)[:：]?$/;
const backgroundLabel = /^(公司|部门|团队|技术团队|业务线|产品线|事业群)[:：].+$/;
const backgroundName = /^.{1,20}(团队|部门|事业群|业务线|产品线)$/;

export function isJobBackground(item: JobRequirement) {
  if (item.inferred) return false;
  const text = item.text.replace(/\s+/g, "").replace(/[-:：；;。]+$/g, "");
  const hasCandidateCue = candidateCues.some((cue) => text.includes(cue));
  return !text || heading.test(text) || backgroundLabel.test(text) || (backgroundName.test(text) && !hasCandidateCue) || /^(团队|部门|技术团队).{0,18}(是|为|负责|服务|致力于)/.test(text) || (backgroundCues.some((cue) => text.includes(cue)) && !hasCandidateCue);
}

function isRecommended(item: JobRequirement) {
  return item.confirmationStatus === "pending" && !item.inferred && Boolean(item.sourceQuote) && !isJobBackground(item);
}

function kindLabel(item: JobRequirement) {
  if (item.priority === "nice_to_have") return "加分项";
  return { responsibility: "岗位职责", skill: "技能要求", experience: "经验要求", project: "项目偏好" }[item.requirementType] ?? "岗位要求";
}

function preparationCopy(item: JobRequirement) {
  return item.preparationStatus === "reliable_evidence" ? "已有可靠经历支持" : item.preparationStatus === "profile_incomplete" ? "资料还不完整，建议补充后再判断" : item.preparationStatus === "no_experience" ? "暂未找到相关经历" : "建议通过项目深挖补充证据和表达";
}

export function RequirementWorkbench({ requirements, busy = false, onDecide }: { requirements: JobRequirement[]; busy?: boolean; onDecide: (ids: string[], decision: "pending" | "confirmed" | "rejected") => void }) {
  const [checkedIds, setCheckedIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [view, setView] = useState<RequirementView>("pending");
  const background = useMemo(() => requirements.filter(isJobBackground), [requirements]);
  const actionable = useMemo(() => requirements.filter((item) => !isJobBackground(item)), [requirements]);
  const pending = useMemo(() => actionable.filter((item) => item.confirmationStatus === "pending"), [actionable]);
  const confirmed = useMemo(() => actionable.filter((item) => item.confirmationStatus === "confirmed"), [actionable]);
  const rejected = useMemo(() => actionable.filter((item) => item.confirmationStatus === "rejected"), [actionable]);
  const visible = view === "pending" ? pending : view === "confirmed" ? confirmed : rejected;
  const recommended = useMemo(() => pending.filter(isRecommended), [pending]);
  const manual = useMemo(() => pending.filter((item) => !isRecommended(item)), [pending]);
  const active = visible.find((item) => item.id === activeId) ?? visible[0] ?? null;

  useEffect(() => {
    const actionableIds = new Set(actionable.map((item) => item.id));
    setCheckedIds((current) => current.filter((id) => actionableIds.has(id)));
  }, [actionable]);
  useEffect(() => {
    setCheckedIds([]);
  }, [view]);
  useEffect(() => {
    if (activeId && visible.some((item) => item.id === activeId)) return;
    setActiveId(visible[0]?.id ?? null);
  }, [activeId, visible]);

  function toggle(id: string) {
    setCheckedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  const selectedCopy = view === "pending"
    ? `已选 ${checkedIds.length} 条 · 推荐确认 ${recommended.length} 条 · 人工确认 ${manual.length} 条`
    : `已选 ${checkedIds.length} 条`;

  return <section className="requirement-workbench">
    <header>
      <div><span className="requirement-workbench__eyebrow">确认真正影响准备方向的门槛</span><h2>岗位要求</h2><p>团队介绍与业务背景只用于理解岗位，不会进入确认或准备度计算。</p></div>
      <div className="requirement-workbench__header-actions"><span><b>{pending.length}</b> 条待确认 · {background.length} 条岗位背景</span>{view === "pending" ? <Button disabled={!recommended.length || busy} onClick={() => onDecide(recommended.map((item) => item.id), "confirmed")}>一键确认推荐项</Button> : view === "confirmed" ? <Button variant="secondary" disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "pending")}>批量撤回确认</Button> : <Button variant="secondary" disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "pending")}>批量恢复待确认</Button>}</div>
    </header>
    <div className="requirement-workbench__controls">
      <div className="requirement-workbench__views" role="tablist" aria-label="岗位要求状态筛选">
        <button type="button" role="tab" aria-selected={view === "pending"} onClick={() => setView("pending")}>待确认 <b>{pending.length}</b></button>
        <button type="button" role="tab" aria-selected={view === "confirmed"} onClick={() => setView("confirmed")}>已确认 <b>{confirmed.length}</b></button>
        <button type="button" role="tab" aria-selected={view === "rejected"} onClick={() => setView("rejected")}>已忽略 <b>{rejected.length}</b></button>
      </div>
      {background.length ? <details className="requirement-workbench__background"><summary>了解岗位背景 <span>{background.length} 条</span></summary><p>{background.map((item) => item.text).join(" · ")}</p></details> : null}
    </div>
    {view === "pending" && manual.length ? <p className="requirement-workbench__notice">{manual.length} 条内容需要人工确认：它们来自模型推断，或无法精确对应到岗位原文。</p> : null}
    <div className="requirement-workbench__body">
      <div className="requirement-workbench__queue" aria-label="岗位要求列表">
        {visible.length ? visible.map((item) => {
          const pendingItem = item.confirmationStatus === "pending";
          const recommendation = isRecommended(item);
          return <article key={item.id} className={active?.id === item.id ? "is-active" : ""}>
            <input type="checkbox" aria-label={`选择：${item.text}`} checked={checkedIds.includes(item.id)} disabled={busy} onChange={() => toggle(item.id)} />
            <button type="button" className="requirement-workbench__item-main" onClick={() => setActiveId(item.id)}><span>{kindLabel(item)}</span><strong>{item.text}</strong>{pendingItem && <i className={recommendation ? "is-recommended" : "is-manual"}>{recommendation ? "推荐确认" : "人工确认"}</i>}</button>
            <em>{pendingItem ? "待确认" : item.confirmationStatus === "confirmed" ? "已确认" : "已忽略"}</em>
            {pendingItem ? <div className="requirement-workbench__item-actions"><Button size="sm" disabled={busy} onClick={() => onDecide([item.id], "confirmed")}>确认</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onDecide([item.id], "rejected")}>忽略</Button></div> : null}
          </article>;
        }) : <div className="requirement-workbench__empty"><strong>{view === "pending" ? "当前没有待确认要求" : view === "confirmed" ? "还没有已确认要求" : "还没有已忽略要求"}</strong><p>{view === "pending" ? "可以查看已确认内容，或重新分析岗位描述。" : "切换到待确认继续处理。"}</p></div>}
      </div>
      <article className="requirement-workbench__detail">
        {active ? <><div className="requirement-workbench__detail-heading"><div><span>{kindLabel(active)}</span><h3>{active.text}</h3></div>{active.confirmationStatus === "pending" ? <div><Button disabled={busy} onClick={() => onDecide([active.id], "confirmed")}>确认这条</Button><Button variant="secondary" disabled={busy} onClick={() => onDecide([active.id], "rejected")}>忽略</Button></div> : <div><Button variant="secondary" disabled={busy} onClick={() => onDecide([active.id], "pending")}>{active.confirmationStatus === "confirmed" ? "撤回确认" : "恢复待确认"}</Button></div>}</div><section><h4>原文依据</h4><blockquote>{active.sourceQuote || "这是系统根据上下文推断的内容，没有直接原文。"}</blockquote></section><section><h4>确认建议</h4><p>{isRecommended(active) ? "原文明确且可独立理解，建议直接确认。" : "请先核对是否符合岗位真实要求，再决定确认或忽略。"}</p></section><section><h4>你的准备情况</h4><p>{preparationCopy(active)}</p></section>{active.confirmationStatus !== "pending" ? <p className="requirement-workbench__reversible-note">{active.confirmationStatus === "confirmed" ? "撤回后，这条要求会回到待确认，不再参与当前准备判断。" : "恢复后，这条要求会回到待确认，等待你重新判断。"}</p> : null}</> : <div className="requirement-workbench__empty"><strong>选择一条要求查看详情</strong><p>详情会显示原文依据和你的准备情况。</p></div>}
      </article>
    </div>
    <footer><span>{selectedCopy}</span><div>{view === "pending" ? <><Button variant="secondary" disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "rejected")}>忽略所选</Button><Button disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "confirmed")}>确认所选</Button></> : view === "confirmed" ? <Button variant="secondary" disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "pending")}>撤回所选确认</Button> : <Button variant="secondary" disabled={!checkedIds.length || busy} onClick={() => onDecide(checkedIds, "pending")}>恢复所选待确认</Button>}</div></footer>
  </section>;
}
