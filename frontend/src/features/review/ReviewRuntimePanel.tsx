import { Activity, Brain, FileCheck2, Gauge } from "lucide-react";
import type { ReviewRound } from "./reviewTypes";

export function ReviewRuntimePanel({ round }: { round: ReviewRound | null }) {
  const latest = round?.attempts.at(-1);
  const stage = latest?.status === "evaluating" ? "正在评价回答" : latest?.status === "evaluation_failed" ? "评价失败，可重试" : round?.currentInput ? "等待你的回答" : round?.status ?? "未选择轮次";
  return <aside className="review-runtime-panel" aria-label="轮次运行状态"><div className="review-pane-title"><Activity size={16} /><strong>运行状态</strong></div>{round ? <><div className="review-runtime-stage"><small>当前阶段</small><strong>{stage}</strong></div><dl className="runtime-facts"><div><dt>轮次</dt><dd>{round.currentIndex}/{round.questionCount}</dd></div><div><dt>状态</dt><dd>{round.status}</dd></div><div><dt>模型</dt><dd>{round.settings.answer_model_id}</dd></div><div><dt>思考强度</dt><dd>{round.settings.reasoning_effort}</dd></div></dl><div className="runtime-meter"><Gauge size={16} /><span>{round.usage.totalTokens} tokens · {round.usage.callCount} calls</span></div><div className="runtime-meter"><Brain size={16} /><span>{round.attempts.filter((item) => item.masterySuggestion === "stable" || item.masterySuggestion === "strong").length} 项稳定掌握</span></div><div className="runtime-meter"><FileCheck2 size={16} /><span>{round.executionStatus === "waiting_for_approval" ? "报告等待确认" : "产物随轮次生成"}</span></div></> : <p className="status-note">选择轮次后显示模型、阶段、用量和掌握度。</p>}</aside>;
}
