import { Activity, BookOpenCheck, BrainCircuit, ShieldCheck } from "lucide-react";
import type { CSSProperties } from "react";
import type { DeepDiveResource } from "./jobTargetTypes";

const stages: Record<string, string> = {
  background: "项目背景",
  role: "个人职责",
  solution: "方案设计",
  difficulty: "难点解决",
  outcome: "结果成效",
  tradeoff: "取舍与复盘",
  target_follow_up: "岗位追问",
  finished: "已完成",
};

const gapActions: Record<string, string> = {
  knowledge: "生成项目题",
  expression: "整理讲解建议",
  experience: "标记为已知风险",
  profile: "去个人资料补充",
};

function formatContextTokens(value: number) {
  return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
}

export function DeepDiveContextPanel({ resource, onDispatchGap, onOpenProfile }: { resource: DeepDiveResource; onDispatchGap: (gap: DeepDiveResource["gaps"][number]) => void; onOpenProfile: () => void }) {
  const statusLabel = { active: "进行中", paused: "已暂停", interrupted: "已中断", completed: "已完成", terminated: "已结束" }[resource.status] ?? resource.status;
  const contextPercent = resource.runtime.contextThreshold > 0
    ? Math.min(100, Math.round(resource.runtime.contextTokens / resource.runtime.contextThreshold * 100))
    : 0;
  const deltas = resource.artifacts.flatMap((item) => {
    const value = item.payload.narrativeDelta;
    return Array.isArray(value) ? value as { section: string; content: string }[] : [];
  });
  return <div className="deep-dive-context">
    <header><span><BrainCircuit size={18} /></span><div><strong>项目教练状态</strong><p>回答会逐步沉淀为项目讲解与追问题。</p></div></header>
    <section className="deep-dive-context__status"><div><Activity size={16} /><span>会话状态</span><strong>{statusLabel}</strong></div><div><BookOpenCheck size={16} /><span>当前环节</span><strong>{stages[resource.currentStage] ?? resource.currentStage}</strong></div></section>
    <section><h3>本次参考范围</h3><p><ShieldCheck size={15} />仅使用当前目标岗位、当前项目和已确认个人资料。</p></section>
    <section><h3>项目讲解草稿 <span>{resource.completedStageIds.length} 个维度</span></h3>{deltas.length ? deltas.map((item, index) => <div className="deep-dive-context__draft" key={`${item.section}-${index}`}><b>{stages[item.section] ?? item.section}</b><p>{item.content}</p></div>) : <p>回答问题后，这里会逐步形成可复用的项目讲解。</p>}</section>
    <section><h3>待处理建议 <span>{resource.gaps.filter((item) => item.status === "open").length} 条</span></h3>{resource.gaps.filter((item) => item.status === "open").length ? <div className="deep-dive-context__gaps">{resource.gaps.filter((item) => item.status === "open").map((gap) => <button type="button" key={gap.id} onClick={() => gap.gap_kind === "profile" ? onOpenProfile() : onDispatchGap(gap)}><strong>{gap.summary}</strong><span>{gapActions[gap.gap_kind] ?? "处理建议"}</span></button>)}</div> : <p>当前没有需要处理的建议。</p>}</section>
    <details><summary>模型与上下文</summary><div className="deep-dive-context__runtime"><div className="deep-dive-context__ring" style={{ "--context-progress": `${contextPercent * 3.6}deg` } as CSSProperties}><span>{contextPercent}%</span></div><dl><div><dt>模型调用</dt><dd>{resource.runtime.calls} 次</dd></div><div><dt>Token</dt><dd>{resource.runtime.inputTokens + resource.runtime.outputTokens}{resource.runtime.estimated ? "（估算）" : ""}</dd></div><div><dt>上下文</dt><dd>{formatContextTokens(resource.runtime.contextTokens)} / {resource.runtime.contextThreshold > 0 ? formatContextTokens(resource.runtime.contextThreshold) : "未设置"}</dd></div><div><dt>压缩</dt><dd>{resource.runtime.compacted ? "已压缩" : "未触发"}</dd></div></dl></div></details>
  </div>;
}
