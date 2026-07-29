import { CheckCircle2, CircleAlert, LoaderCircle } from "lucide-react";
import type { EvaluationRun } from "./evaluationTypes";


interface EvaluationRunListProps {
  runs: EvaluationRun[];
  selectedId: string | null;
  compareIds: string[];
  onSelect: (id: string) => void;
  onToggleCompare: (id: string) => void;
}

export function EvaluationRunList({
  runs,
  selectedId,
  compareIds,
  onSelect,
  onToggleCompare,
}: EvaluationRunListProps) {
  if (runs.length === 0) {
    return <p className="evaluation-empty">还没有质量评估。可从运行详情发起 Judge。</p>;
  }
  return (
    <ul className="evaluation-run-list">
      {runs.map((run) => (
        <li key={run.id} data-selected={run.id === selectedId}>
          <button type="button" onClick={() => onSelect(run.id)}>
            <span aria-hidden="true">
              {run.status === "completed" ? <CheckCircle2 /> : run.status === "running" ? <LoaderCircle /> : <CircleAlert />}
            </span>
            <span>
              <strong>{run.evalPackId}</strong>
              <small>v{run.evalPackVersion} · {run.trigger === "manual" ? "手动" : run.trigger === "automatic" ? "自动" : "回归"} · {run.status}</small>
            </span>
          </button>
          <label>
            <input
              type="checkbox"
              checked={compareIds.includes(run.id)}
              disabled={!compareIds.includes(run.id) && compareIds.length >= 2}
              onChange={() => onToggleCompare(run.id)}
            />
            对比
          </label>
        </li>
      ))}
    </ul>
  );
}
