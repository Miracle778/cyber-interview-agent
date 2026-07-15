import { ArrowRight, BookOpenCheck, CalendarDays, Plus, TriangleAlert } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound } from "./reviewTypes";

const statusText: Record<string, string> = { waiting_for_input: "等待回答", running: "进行中", report_pending: "报告待确认", completed: "已完成", failed: "失败", cancelled: "已结束" };
const RECOMMENDED_QUESTION_COUNT = 10;

export function ReviewLanding({ rounds, questionCount, onCreate, onOpen, onCatalog }: { rounds: ReviewRound[]; questionCount: number | null; onCreate: () => void; onOpen: (id: string) => void; onCatalog: () => void }) {
  const active = rounds.filter((round) => !["completed", "cancelled", "failed"].includes(round.status));
  const ordered = [...active, ...rounds.filter((round) => !active.includes(round))];
  return <main className="review-landing">
    <header><div><span>复习 Agent</span><h2>复习历史</h2><p>先回到任何未完成轮次，或显式创建一轮新的复习。</p></div><Button onClick={onCreate} loading={questionCount === null} disabled={questionCount === 0}><Plus size={16} />创建复习</Button></header>
    {questionCount === 0 ? <section className="review-readiness review-readiness--empty" role="status" aria-label="题库尚未准备好"><span className="review-readiness__icon"><BookOpenCheck size={20} /></span><div><h3>先准备可复习题目</h3><p>当前没有已确认题目。先导入资料并完成题库整理，确认后的题目才能进入复习轮次。</p></div><Button onClick={onCatalog}><BookOpenCheck size={16} />去题库整理</Button></section> : null}
    {questionCount !== null && questionCount > 0 && questionCount < RECOMMENDED_QUESTION_COUNT ? <section className="review-readiness review-readiness--low" role="status" aria-label="题库题量偏少"><span className="review-readiness__icon"><TriangleAlert size={20} /></span><div><h3>当前题库有 {questionCount} 道题</h3><p>可以先创建小轮次；建议补充到 {RECOMMENDED_QUESTION_COUNT} 道以上，让选题和复习节奏更稳定。</p></div><Button variant="secondary" onClick={onCatalog}>补充题库</Button></section> : null}
    <section className="review-landing__summary" aria-label="复习历史概览"><div><strong>{active.length}</strong><span>进行中</span></div><div><strong>{rounds.filter((item) => item.status === "completed").length}</strong><span>已完成</span></div><div><strong>{rounds.reduce((sum, item) => sum + item.attempts.length, 0)}</strong><span>累计回答</span></div></section>
    <section className="review-landing__list" aria-label="历史复习轮次">
      {ordered.length === 0 ? <div className="review-landing__empty"><CalendarDays size={28} /><h3>还没有复习记录</h3><p>{questionCount === 0 ? "题库准备好后，从这里创建第一轮复习。" : "创建第一轮后，这里会保留所有进度和评价。"}</p></div> : ordered.map((round) => <button type="button" key={round.id} onClick={() => onOpen(round.id)}><div><strong>{round.questionCount} 题 · {round.settings.mode}</strong><small>{round.settings.difficulties.join(" / ")} · {round.settings.answer_model_id}</small></div><span>{statusText[round.status] ?? round.status} · {round.currentIndex}/{round.questionCount}</span><ArrowRight size={17} /></button>)}
    </section>
  </main>;
}
