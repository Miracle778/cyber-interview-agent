import { ArrowRight, CalendarDays, Plus } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound } from "./reviewTypes";

const statusText: Record<string, string> = { waiting_for_input: "等待回答", running: "进行中", report_pending: "报告待确认", completed: "已完成", failed: "失败", cancelled: "已结束" };

export function ReviewLanding({ rounds, onCreate, onOpen }: { rounds: ReviewRound[]; onCreate: () => void; onOpen: (id: string) => void }) {
  const active = rounds.filter((round) => !["completed", "cancelled", "failed"].includes(round.status));
  const ordered = [...active, ...rounds.filter((round) => !active.includes(round))];
  return <main className="review-landing">
    <header><div><span>复习 Agent</span><h2>复习历史</h2><p>先回到任何未完成轮次，或显式创建一轮新的复习。</p></div><Button onClick={onCreate}><Plus size={16} />创建复习</Button></header>
    <section className="review-landing__summary" aria-label="复习历史概览"><div><strong>{active.length}</strong><span>进行中</span></div><div><strong>{rounds.filter((item) => item.status === "completed").length}</strong><span>已完成</span></div><div><strong>{rounds.reduce((sum, item) => sum + item.attempts.length, 0)}</strong><span>累计回答</span></div></section>
    <section className="review-landing__list" aria-label="历史复习轮次">
      {ordered.length === 0 ? <div className="review-landing__empty"><CalendarDays size={28} /><h3>还没有复习记录</h3><p>创建第一轮后，这里会保留所有进度和评价。</p></div> : ordered.map((round) => <button type="button" key={round.id} onClick={() => onOpen(round.id)}><div><strong>{round.questionCount} 题 · {round.settings.mode}</strong><small>{round.settings.difficulties.join(" / ")} · {round.settings.answer_model_id}</small></div><span>{statusText[round.status] ?? round.status} · {round.currentIndex}/{round.questionCount}</span><ArrowRight size={17} /></button>)}
    </section>
  </main>;
}
