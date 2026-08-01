import { CircleCheck, CirclePause, LoaderCircle, RefreshCw, RotateCcw, Square } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { AnalysisRun } from "./retrospectiveTypes";

const ACTIVE = new Set(["queued", "running", "stopping"]);

function stageLabel(run: AnalysisRun) {
  if (run.status === "completed") return "复盘分析已完成";
  if (run.status === "failed") return "分析中断，已有结果仍然保留";
  if (run.status === "stopped") return "分析已停止，随时可以继续";
  if (run.stage === "question_extraction") return "正在识别面试问题";
  if (run.stage === "question_analysis") return `正在分析第 ${Math.min(run.completedItems + 1, Math.max(run.totalItems, 1))} 个问题`;
  if (run.stage === "finalizing") return "正在整理复盘结论";
  return "分析任务正在排队";
}

export function AnalysisProgress({ run, busy, onStop, onResume, onRetry }: {
  run: AnalysisRun;
  busy: boolean;
  onStop: () => void;
  onResume: () => void;
  onRetry: () => void;
}) {
  const active = ACTIVE.has(run.status);
  const percent = run.totalItems > 0 ? Math.min(100, Math.round((run.completedItems / run.totalItems) * 100)) : 0;
  const StatusIcon = run.status === "completed" ? CircleCheck : run.status === "stopped" ? CirclePause : run.status === "failed" ? RefreshCw : LoaderCircle;
  return <section className="analysis-progress" data-status={run.status} aria-live="polite">
    <div className="analysis-progress__status">
      <span><StatusIcon size={20} aria-hidden="true" /></span>
      <div><strong>{stageLabel(run)}</strong><small>{active && run.completedItems > 0 ? "分析仍在继续，已完成的问题可以先看" : "刷新或离开不会丢失已完成结果"}</small></div>
    </div>
    <div className="analysis-progress__meter">
      <div><span>分析进度</span><strong>已完成 {run.completedItems} / {run.totalItems}</strong></div>
      <div role="progressbar" aria-label="分析进度" aria-valuemin={0} aria-valuemax={run.totalItems || 1} aria-valuenow={run.completedItems}><span style={{ width: `${percent}%` }} /></div>
    </div>
    <div className="analysis-progress__actions">
      {active ? <Button size="sm" variant="secondary" onClick={onStop} disabled={busy || run.status === "stopping"}><Square size={15} /> 停止分析</Button> : null}
      {run.status === "stopped" ? <Button size="sm" onClick={onResume} disabled={busy}><RotateCcw size={15} /> 继续分析</Button> : null}
      {run.status === "failed" ? <Button size="sm" onClick={onRetry} disabled={busy}><RefreshCw size={15} /> 重试失败步骤</Button> : null}
    </div>
  </section>;
}
