import { History } from "lucide-react";
import type { ReviewRound } from "./reviewTypes";

export function ReviewHistory({ rounds, selectedId, onSelect }: { rounds: ReviewRound[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <nav className="review-history" aria-label="复习轮次历史">
      <div className="review-pane-title"><History size={16} /><strong>轮次历史</strong><span>{rounds.length}</span></div>
      {rounds.length === 0 ? <p className="status-note">还没有复习轮次</p> : null}
      {rounds.map((round) => (
        <button key={round.id} type="button" className="review-history__item" aria-current={round.id === selectedId} onClick={() => onSelect(round.id)}>
          <span>{round.questionCount} 题 · {round.settings.mode}</span>
          <small>{round.status} · {new Date(round.updatedAt).toLocaleDateString("zh-CN")}</small>
        </button>
      ))}
    </nav>
  );
}
