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

export function DeepDiveContextPanel({ resource }: { resource: DeepDiveResource }) {
  const deltas = resource.artifacts.flatMap((item) => {
    const value = item.payload.narrativeDelta;
    return Array.isArray(value) ? value as { section: string; content: string }[] : [];
  });
  return <div className="deep-dive-context">
    <section><h3>本次参考范围</h3><p>仅使用当前目标岗位、当前项目和已确认个人资料。</p></section>
    <section><h3>当前项目与阶段</h3><strong>{stages[resource.currentStage] ?? resource.currentStage}</strong><p>已完成 {resource.completedStageIds.length} 个讲解维度</p></section>
    <section><h3>项目讲解草稿</h3>{deltas.length ? deltas.map((item, index) => <div key={`${item.section}-${index}`}><b>{stages[item.section] ?? item.section}</b><p>{item.content}</p></div>) : <p>回答问题后，这里会逐步形成可复用的项目讲解。</p>}</section>
    <section><h3>待处理建议</h3><p>{resource.gaps.filter((item) => item.status === "open").length} 条需要补充或确认</p></section>
    <section><h3>运行状态</h3><dl><div><dt>状态</dt><dd>{resource.status}</dd></div><div><dt>模型调用</dt><dd>{resource.runtime.calls} 次</dd></div></dl></section>
    <details><summary>技术详情</summary><dl><div><dt>模型用途</dt><dd>项目深挖</dd></div><div><dt>Token</dt><dd>{resource.runtime.inputTokens + resource.runtime.outputTokens}{resource.runtime.estimated ? "（估算）" : ""}</dd></div><div><dt>上下文</dt><dd>{resource.runtime.contextTokens} / {resource.runtime.contextThreshold || "未设置"}</dd></div><div><dt>压缩</dt><dd>{resource.runtime.compacted ? "已压缩" : "未触发"}</dd></div></dl></details>
  </div>;
}
