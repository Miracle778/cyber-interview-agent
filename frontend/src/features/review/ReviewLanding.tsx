import { Archive, ArrowRight, BookOpenCheck, CalendarDays, Plus, RotateCcw, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import { formatBeijingTimestamp } from "../../shared/time";
import type { ReviewRound } from "./reviewTypes";
import { reviewScopeTitle } from "./reviewScope";

const statusText: Record<string, string> = { waiting_for_input: "等待回答", running: "进行中", report_pending: "报告待确认", completed: "已完成", failed: "失败", cancelled: "已结束" };
const RECOMMENDED_QUESTION_COUNT = 10;
const modeText = { "random-mixed": "随机混合", "weak-point": "薄弱优先", "topic-focused": "专题复习", "recent-mistake": "近期错题", "source-file": "按资料复习" } as const;
const difficultyText = { easy: "简单", medium: "中等", hard: "困难" } as const;
type HistoryFilter = "all" | "active" | "completed" | "ended" | "answered";

function roundDate(value: string) {
  const timestamp = formatBeijingTimestamp(value, {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return timestamp?.replace(/^(\d+)\/(\d+)\s/, "$1月$2日 ") ?? "";
}

function RoundRow({ round, onOpen, onArchive, archived = false, onRestore }: { round: ReviewRound; onOpen: () => void; onArchive?: () => void; archived?: boolean; onRestore?: () => void }) {
  const completed = round.attempts.filter((attempt) => attempt.status === "completed").length;
  const terminal = ["completed", "cancelled", "failed"].includes(round.status);
  const stage = !terminal && round.executionStatus === "failed" ? "需要恢复" : statusText[round.status] ?? round.status;
  return <article className="review-history-row"><button type="button" className="review-history-row__open" onClick={onOpen}><div><strong>{reviewScopeTitle(round)} · {round.questionCount} 题</strong><small>{modeText[round.settings.mode]} · {round.settings.difficulties.map((item) => `${difficultyText[item]}难度`).join(" / ")}{roundDate(round.createdAt) ? ` · ${roundDate(round.createdAt)}` : ""}</small></div><span>{stage} · 已完成 {completed}/{round.questionCount}</span><ArrowRight size={17} /></button>{archived ? <Button size="sm" variant="ghost" onClick={onRestore}><RotateCcw size={15} />恢复</Button> : terminal ? <Button size="sm" variant="ghost" onClick={onArchive}><Archive size={15} />归档</Button> : null}</article>;
}

export function ReviewLanding({ rounds, questionCount, onCreate, onOpen, onCatalog, onArchive, onRestore }: { rounds: ReviewRound[]; questionCount: number | null; onCreate: () => void; onOpen: (id: string) => void; onCatalog: () => void; onArchive: (round: ReviewRound) => void; onRestore: (round: ReviewRound) => void }) {
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const current = rounds.filter((round) => !round.archivedAt);
  const archived = rounds.filter((round) => Boolean(round.archivedAt));
  const active = current.filter((round) => !["completed", "cancelled", "failed"].includes(round.status));
  const completedRounds = current.filter((round) => round.status === "completed");
  const ended = current.filter((round) => ["cancelled", "failed"].includes(round.status));
  const answeredItems = current.flatMap((round) => round.attempts.filter((attempt) => !attempt.skipped && Boolean(attempt.answer?.trim())).map((attempt) => ({ round, attempt })));
  const filteredRounds = filter === "active" ? active : filter === "completed" ? completedRounds : filter === "ended" ? ended : current;
  const ordered = [...filteredRounds.filter((round) => active.includes(round)), ...filteredRounds.filter((round) => !active.includes(round))];
  const metrics = [{ key: "active", value: active.length, label: "进行中" }, { key: "completed", value: completedRounds.length, label: "已完成" }, { key: "ended", value: ended.length, label: "已结束" }, { key: "answered", value: answeredItems.length, label: "已作答题目" }] as const;
  return <main className="review-landing">
    <header><div><span>复习 Agent</span><h2>复习历史</h2><p>先回到任何未完成轮次，或显式创建一轮新的复习。</p></div><Button onClick={onCreate} loading={questionCount === null} disabled={questionCount === 0}><Plus size={16} />创建复习</Button></header>
    {questionCount === 0 ? <section className="review-readiness review-readiness--empty" role="status" aria-label="题库尚未准备好"><span className="review-readiness__icon"><BookOpenCheck size={20} /></span><div><h3>先准备可复习题目</h3><p>当前没有已确认题目。先导入资料并完成题库整理，确认后的题目才能进入复习轮次。</p></div><Button onClick={onCatalog}><BookOpenCheck size={16} />去题库整理</Button></section> : null}
    {questionCount !== null && questionCount > 0 && questionCount < RECOMMENDED_QUESTION_COUNT ? <section className="review-readiness review-readiness--low" role="status" aria-label="题库题量偏少"><span className="review-readiness__icon"><TriangleAlert size={20} /></span><div><h3>当前题库有 {questionCount} 道题</h3><p>可以先创建小轮次；建议补充到 {RECOMMENDED_QUESTION_COUNT} 道以上，让选题和复习节奏更稳定。</p></div><Button variant="secondary" onClick={onCatalog}>补充题库</Button></section> : null}
    <section className="review-landing__summary" aria-label="复习历史概览">{metrics.map((metric) => <button type="button" key={metric.key} aria-pressed={filter === metric.key} aria-label={`${metric.label} ${metric.value}，点击查看条目`} onClick={() => setFilter((currentFilter) => currentFilter === metric.key ? "all" : metric.key)}><strong>{metric.value}</strong><span>{metric.label}</span></button>)}</section>
    <section className="review-landing__history" aria-label="复习历史与归档">
      <section className="review-landing__list" aria-label="历史复习轮次">
        <div className="review-history-filter"><span>{filter === "all" ? "全部未归档轮次" : `当前筛选：${metrics.find((item) => item.key === filter)?.label}`}</span><strong>{filter === "answered" ? answeredItems.length : ordered.length} 条</strong></div>
        {filter === "answered" ? answeredItems.map(({ round, attempt }) => <button type="button" className="review-answer-history-row" key={`${round.id}-${attempt.id}`} onClick={() => onOpen(round.id)}><span>第 {attempt.ordinal} 题</span><strong>{attempt.questionSnapshot.title}</strong><small>{attempt.answer}</small><ArrowRight size={16} /></button>) : ordered.length === 0 ? <div className="review-landing__empty"><CalendarDays size={28} /><h3>{filter === "all" ? "还没有复习记录" : "这个分类暂无记录"}</h3><p>{questionCount === 0 ? "题库准备好后，从这里创建第一轮复习。" : "创建第一轮后，这里会保留所有进度和评价。"}</p></div> : ordered.map((round) => <RoundRow key={round.id} round={round} onOpen={() => onOpen(round.id)} onArchive={() => onArchive(round)} />)}
      </section>
      {archived.length ? <details className="review-archive"><summary><span><Archive size={16} />已归档</span><strong>{archived.length}</strong></summary><div>{archived.map((round) => <RoundRow key={round.id} round={round} archived onOpen={() => onOpen(round.id)} onRestore={() => onRestore(round)} />)}</div></details> : null}
    </section>
  </main>;
}
