import { History } from "lucide-react";
import { formatBeijingDate } from "../../shared/time";
import type { ReviewRound } from "./reviewTypes";
import { reviewScopeTitle } from "./reviewScope";

function progressLabel(round: ReviewRound): string {
  if (round.status === "completed") {
    return `${round.questionCount}/${round.questionCount} 已完成`;
  }
  if (["cancelled", "failed"].includes(round.status)) {
    return `${Math.min(round.currentIndex, round.questionCount)}/${round.questionCount} 已作答`;
  }
  return `第 ${Math.min(round.currentIndex + 1, round.questionCount)}/${round.questionCount} 题`;
}

export function ReviewHistory({ rounds, selectedId, onSelect }: { rounds: ReviewRound[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const ordered = [...rounds].sort((left, right) => {
    const terminal = new Set(["completed", "cancelled", "failed"]);
    return Number(terminal.has(left.status)) - Number(terminal.has(right.status));
  });
  return (
    <nav className="review-history" aria-label="复习轮次历史">
      <div className="review-pane-title"><History size={16} /><strong>轮次历史</strong><span>{rounds.length}</span></div>
      {rounds.length === 0 ? <p className="status-note">还没有复习轮次</p> : null}
      {ordered.map((round) => (
        <button key={round.id} type="button" className="review-history__item" aria-current={round.id === selectedId} onClick={() => onSelect(round.id)}>
          <strong>{reviewScopeTitle(round)} · {round.questionCount} 题</strong>
          <span>{progressLabel(round)}</span>
          <small>{round.status} · {formatBeijingDate(round.updatedAt) ?? round.updatedAt}</small>
        </button>
      ))}
    </nav>
  );
}
