import { BarChart3, MessageCircle } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import type { ReviewRound } from "./reviewTypes";
import { ReviewChatMessage } from "./ReviewConversation";

export function ReviewResults({ round, onDiscuss }: { round: ReviewRound; onDiscuss: (ordinal: number) => void }) {
  const good = round.attempts.filter((item) => item.evaluation?.score === "good").length;
  const completed = round.attempts.filter((item) => item.status === "completed").length;
  const [view, setView] = useState<"report" | "replay">("report");
  const [filter, setFilter] = useState<"all" | "completed" | "good" | "skipped">("all");
  const scoreText = { good: "掌握良好", partial: "部分掌握", poor: "需要加强" } as const;
  const publicationText: Record<string, string> = { published: "已发布", review_pending: "待确认", index_stale: "索引待更新", failed: "发布失败" };
  const skipped = round.attempts.filter((item) => item.skipped).length;
  const visibleAttempts = round.attempts.filter((attempt) => filter === "all" || (filter === "completed" && attempt.status === "completed") || (filter === "good" && attempt.evaluation?.score === "good") || (filter === "skipped" && attempt.skipped));
  const replayMessages = round.messages.length ? round.messages : round.attempts.flatMap((attempt) => [
    { id: `${attempt.id}-prompt`, executionId: round.executionId, role: "assistant", content: attempt.questionSnapshot.questionText, messageKind: "review_prompt", payload: {}, createdAt: round.createdAt },
    { id: `${attempt.id}-answer`, executionId: round.executionId, role: "user", content: attempt.skipped ? "已跳过本题" : attempt.answer || "未作答", messageKind: "review_answer", payload: {}, createdAt: round.createdAt },
    ...(attempt.evaluation ? [{ id: `${attempt.id}-evaluation`, executionId: round.executionId, role: "assistant", content: attempt.evaluation.evidence, messageKind: "evaluation_card", payload: { evaluation: attempt.evaluation }, createdAt: round.updatedAt }] : []),
  ]);
  return (
    <Card title="本轮复习结果" icon={<BarChart3 size={18} />}>
      <div className="review-result-tabs" role="tablist" aria-label="复习结果视图"><button type="button" role="tab" aria-selected={view === "report"} onClick={() => setView("report")}>复习报告</button><button type="button" role="tab" aria-selected={view === "replay"} onClick={() => setView("replay")}>会话回放</button></div>
      {view === "replay" ? <div className="review-result-replay review-conversation--chat"><div className="review-chat-log" role="log" aria-label="复习会话回放">{!round.messages.length && round.attempts.length ? <p className="status-note">此历史轮次没有消息投影，以下内容由已保存的作答记录还原。</p> : null}{replayMessages.length ? replayMessages.map((message) => <ReviewChatMessage key={message.id} message={message} />) : <p className="status-note">本轮没有可回放的对话记录。</p>}</div></div> : <>
      <div className="review-result-metrics">{([{ key: "completed", value: completed, label: "已完成" }, { key: "good", value: good, label: "掌握良好" }, { key: "skipped", value: skipped, label: "跳过" }] as const).map((metric) => <button type="button" key={metric.key} aria-pressed={filter === metric.key} aria-label={`${metric.label} ${metric.value}，点击筛选`} onClick={() => setFilter((current) => current === metric.key ? "all" : metric.key)}><strong>{metric.value}</strong><span>{metric.label}</span></button>)}</div>
      <div className="review-result-filter-meta"><span>{filter === "all" ? "全部题目" : `已筛选：${filter === "completed" ? "已完成" : filter === "good" ? "掌握良好" : "跳过"}`}</span><strong>{visibleAttempts.length} 道</strong></div>
      <div className="review-result-list">{visibleAttempts.map((attempt) => <details key={attempt.id}><summary><strong>{attempt.ordinal}. {attempt.questionSnapshot.title}</strong><span>{attempt.skipped ? "已跳过" : attempt.evaluation ? scoreText[attempt.evaluation.score] : "未评价"}</span></summary><div>{attempt.evaluation ? <p>{attempt.evaluation.evidence}</p> : <p className="status-note">本题没有评价结果。</p>}<Button size="sm" variant="ghost" onClick={() => onDiscuss(attempt.ordinal)}><MessageCircle size={14} />深入讨论</Button></div></details>)}</div>
      {round.reports.map((report) => <details className="review-report-artifact" key={report.id}><summary><strong>{report.title}</strong><span>{publicationText[report.publication?.state ?? report.status] ?? "报告草稿"}</span></summary>{report.publication ? <div><span>发布状态：{publicationText[report.publication.state] ?? report.publication.state}</span><code>{report.publication.target_path}</code>{report.publication.state === "index_stale" ? <span role="alert">索引待重新扫描</span> : null}</div> : null}</details>)}
      {round.executionStatus === "waiting_for_approval" ? <p className="status-note">报告与掌握度草稿已生成，人工确认只会在右侧待确认区域出现。</p> : null}
      </>}
    </Card>
  );
}
