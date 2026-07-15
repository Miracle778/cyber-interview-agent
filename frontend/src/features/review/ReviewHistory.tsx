import { History } from "lucide-react";
import type { ReviewRound } from "./reviewTypes";

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
          <strong>{round.questionCount} 题 · {round.settings.mode}</strong>
          <span>{progressLabel(round)}</span>
          <small>{round.status} · {new Date(round.updatedAt).toLocaleDateString("zh-CN")}</small>
        </button>
      ))}
    </nav>
  );
}
