import { AlertTriangle, Bot, CheckCircle2, Clock3, LoaderCircle, PauseCircle, XCircle } from "lucide-react";
import { formatBeijingTime } from "../../shared/time";
import type { ExecutionSummary } from "./observabilityTypes";


export const STATUS_LABELS: Record<string, string> = {
  queued: "等待处理",
  running: "运行中",
  waiting_for_input: "等待输入",
  waiting_for_approval: "等待确认",
  interrupted: "已暂停",
  completed: "已完成",
  partial_success: "部分成功",
  failed: "失败",
  cancelled: "已取消",
};

export function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

export function formatCompactNumber(value: number) {
  if (value < 1000) return String(value);
  const rounded = Math.round(value / 100) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}k`;
}

export function formatDuration(milliseconds: number | null) {
  if (milliseconds === null) return "—";
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "running") return <LoaderCircle size={16} aria-hidden="true" />;
  if (status === "completed") return <CheckCircle2 size={16} aria-hidden="true" />;
  if (status === "failed") return <XCircle size={16} aria-hidden="true" />;
  if (status === "partial_success") return <AlertTriangle size={16} aria-hidden="true" />;
  if (status === "interrupted") return <PauseCircle size={16} aria-hidden="true" />;
  return <Clock3 size={16} aria-hidden="true" />;
}

interface ExecutionListProps {
  executions: ExecutionSummary[];
  selectedId: string | null;
  onSelect: (executionId: string) => void;
}

export function ExecutionList({
  executions,
  selectedId,
  onSelect,
}: ExecutionListProps) {
  return (
    <div className="execution-list" aria-label="Execution 列表">
      <div className="execution-list__header" aria-hidden="true">
        <span>Agent / 运行任务</span>
        <span>状态</span>
        <span>耗时</span>
        <span>Token</span>
        <span>开始时间</span>
      </div>
      {executions.map((execution) => (
        <button
          className="execution-row"
          data-status={execution.status}
          aria-pressed={execution.id === selectedId}
          type="button"
          key={execution.id}
          onClick={() => onSelect(execution.id)}
        >
          <span className="execution-row__identity">
            <span className="execution-row__icon" aria-hidden="true">
              <Bot size={17} />
            </span>
            <span>
              <strong>{execution.title}</strong>
              <small>{execution.displayName}</small>
            </span>
          </span>
          <span className="execution-status" data-status={execution.status}>
            <StatusIcon status={execution.status} />
            {statusLabel(execution.status)}
          </span>
          <span className="execution-row__metric">
            {formatDuration(execution.latencyMs)}
          </span>
          <span className="execution-row__metric">
            {formatCompactNumber(execution.totalTokens)}
          </span>
          <time dateTime={execution.startedAt ?? execution.createdAt}>
            {formatBeijingTime(
              execution.startedAt ?? execution.createdAt,
              false,
            ) ?? "—"}
          </time>
        </button>
      ))}
    </div>
  );
}
