import { useQuery } from "@tanstack/react-query";
import { Activity, BookOpenCheck, ChevronDown, ChevronLeft, ChevronRight, ShieldCheck } from "lucide-react";
import type { CSSProperties } from "react";
import { useState } from "react";
import { listProviders } from "../settings/settingsApi";
import type { ReviewRound } from "./reviewTypes";

const masteryLabel = { unknown: "待评估", weak: "薄弱优先", partial: "部分掌握", stable: "掌握稳定", strong: "掌握良好" } as const;
const reasoningLabel = { none: "默认思考", low: "低强度思考", medium: "中等思考", high: "深入思考" } as const;

function formatTokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : `${value}`;
}

export function ReviewRuntimePanel({ round }: { round: ReviewRound | null }) {
  const [collapsed, setCollapsed] = useState(false);
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const latest = round?.attempts.at(-1);
  const evaluation = latest?.evaluation;
  const mastery = latest?.masterySuggestion ?? evaluation?.mastery_suggestion ?? "unknown";
  const missingPoints = evaluation?.missing_key_points ?? [];
  const currentTokens = round?.contextUsage?.currentTokens ?? 0;
  const thresholdTokens = round?.contextUsage?.thresholdTokens ?? 0;
  const contextPercentage = thresholdTokens > 0 ? Math.min(100, Math.round((currentTokens / thresholdTokens) * 100)) : 0;
  const configuredModel = providers.data?.flatMap((provider) => provider.models.map((model) => ({ provider, model }))).find(({ model }) => model.id === round?.settings.answer_model_id);
  const modelLabel = configuredModel ? `${configuredModel.provider.name} / ${configuredModel.model.displayName}` : round?.settings.answer_model_id ?? "—";
  return <aside className={`review-runtime-panel${collapsed ? " is-collapsed" : ""}`} aria-label="本题反馈">
    <div className="review-pane-title"><strong>{collapsed ? "状态" : "复习状态"}</strong><button type="button" aria-label={collapsed ? "展开复习状态" : "收起复习状态"} aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}</button></div>
    {!collapsed && round ? <div className="review-insight-content">
      <section className="review-mastery-summary"><div><ShieldCheck size={18} /><strong>掌握程度</strong></div><b>{masteryLabel[mastery]}</b><p>{mastery === "weak" ? "建议优先复习本题相关知识点" : mastery === "unknown" ? "完成当前回答后生成掌握度建议" : "根据本轮回答动态更新"}</p></section>
      <details className="curation-runtime-disclosure review-runtime-disclosure is-static" open><summary onClick={(event) => event.preventDefault()}><span><Activity size={16} />运行详情</span><small>{round.usage.callCount} 次调用</small></summary><div className="curation-runtime-disclosure__body"><dl><div><dt>执行状态</dt><dd>{round.executionStatus === "running" ? "处理中" : round.status === "waiting_for_input" ? "等待回答" : "已更新"}</dd></div><div><dt>评价模型</dt><dd title={modelLabel}>{modelLabel}</dd></div><div><dt>思考强度</dt><dd>{reasoningLabel[round.settings.reasoning_effort]}</dd></div><div><dt>Token</dt><dd>{formatTokens(round.usage.totalTokens)}</dd></div></dl><div className="curation-context-compact"><div className="curation-context-ring" style={{ "--context-progress": `${contextPercentage * 3.6}deg` } as CSSProperties}><span>{contextPercentage}%</span></div><div><small>当前上下文 / 压缩阈值</small><strong>{formatTokens(currentTokens)} / {thresholdTokens > 0 ? formatTokens(thresholdTokens) : "—"}</strong></div></div><p className="review-runtime-local-note">查看提示和答案直接读取本轮题库，不调用模型；提交回答后才会统计调用与 Token。</p></div></details>
      <details className="review-runtime-disclosure review-key-points" open><summary><span><BookOpenCheck size={17} />待补充关键点</span><small>{missingPoints.length} 项</small><ChevronDown size={16} /></summary><div>{missingPoints.length ? <ol>{missingPoints.map((point, index) => <li key={`${index}:${point}`} title={point}><span>{index + 1}</span><p>{point}</p></li>)}</ol> : <p className="status-note">评价完成后，这里会列出需要补充的知识点。</p>}</div></details>
    </div> : null}
  </aside>;
}
