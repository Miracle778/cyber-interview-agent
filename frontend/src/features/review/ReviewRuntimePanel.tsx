import { BookOpenCheck, Box, ChevronLeft, ChevronRight, Clock3, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { ReviewRound } from "./reviewTypes";

const masteryLabel = { unknown: "待评估", weak: "薄弱优先", partial: "部分掌握", stable: "掌握稳定", strong: "掌握良好" } as const;
const reasoningLabel = { none: "默认思考", low: "低强度思考", medium: "中等思考", high: "深入思考" } as const;

function displayModel(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value) ? "已绑定评价模型" : value;
}

export function ReviewRuntimePanel({ round }: { round: ReviewRound | null }) {
  const [collapsed, setCollapsed] = useState(false);
  const latest = round?.attempts.at(-1);
  const evaluation = latest?.evaluation;
  const mastery = latest?.masterySuggestion ?? evaluation?.mastery_suggestion ?? "unknown";
  const missingPoints = evaluation?.missing_key_points ?? [];
  return <aside className={`review-runtime-panel${collapsed ? " is-collapsed" : ""}`} aria-label="本题反馈">
    <div className="review-pane-title"><strong>{collapsed ? "反馈" : "本题反馈"}</strong><button type="button" aria-label={collapsed ? "展开本题反馈" : "收起本题反馈"} aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}</button></div>
    {!collapsed && round ? <div className="review-insight-content">
      <section className="review-mastery-summary"><div><ShieldCheck size={18} /><strong>掌握程度</strong></div><b>{masteryLabel[mastery]}</b><p>{mastery === "weak" ? "建议优先复习本题相关知识点" : mastery === "unknown" ? "完成当前回答后生成掌握度建议" : "根据本轮回答动态更新"}</p></section>
      <section className="review-key-points"><div><BookOpenCheck size={18} /><strong>需要补充的关键点</strong></div>{missingPoints.length ? <ol>{missingPoints.map((point, index) => <li key={point}><span>{index + 1}</span><p>{point}</p><em>未覆盖</em></li>)}</ol> : <p className="status-note">评价完成后，这里会列出需要补充的知识点。</p>}</section>
      <section className="review-runtime-fact"><div><Box size={17} /><span>评价模型</span></div><strong>{displayModel(round.settings.answer_model_id)}</strong><small>{reasoningLabel[round.settings.reasoning_effort]}</small></section>
      <section className="review-runtime-fact"><div><Clock3 size={17} /><span>本轮使用</span></div><strong>{round.usage.totalTokens.toLocaleString("zh-CN")} tokens</strong><small>{round.usage.callCount} 次模型调用</small></section>
    </div> : null}
  </aside>;
}
