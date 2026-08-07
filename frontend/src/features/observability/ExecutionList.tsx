import { AlertTriangle, Bot, CheckCircle2, ChevronDown, Clock3, History, LoaderCircle, PauseCircle, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  BEIJING_TIME_ZONE,
  formatBeijingDateTime,
  formatBeijingTime,
  parseApiTimestamp,
} from "../../shared/time";
import type { ExecutionSummary } from "./observabilityTypes";


export const STATUS_LABELS: Record<string, string> = {
  queued: "等待处理",
  running: "运行中",
  waiting_for_input: "等待处理",
  waiting_for_approval: "需要确认",
  interrupted: "已暂停",
  completed: "已完成",
  partial_success: "需要关注",
  failed: "失败待处理",
  cancelled: "已取消",
  recovered: "历史失败·已恢复",
  historical_failed: "历史失败",
  historical_partial: "历史异常",
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

export function executionTaskTitle(execution: ExecutionSummary) {
  const title = execution.title.trim();
  if (/^source_[0-9a-f-]+\.[a-z0-9]+$/i.test(title)) {
    return `${execution.displayName}任务`;
  }
  return title.replace(/\.(md|markdown|txt)$/i, "");
}

export function executionResultSummary(execution: ExecutionSummary) {
  switch (execution.status) {
    case "queued":
      return "任务已进入队列，正在等待开始。";
    case "running":
      return "任务正在处理中，完成后会自动更新结果。";
    case "waiting_for_input":
      return "当前步骤已经完成，正在等待你继续回答或补充信息。";
    case "waiting_for_approval":
      return "结果已经准备好，需要你确认后才能继续。";
    case "partial_success":
      return "部分内容已经完成，仍有问题需要你确认。";
    case "failed":
      return "本次任务没有完成，可以查看原因后继续处理。";
    case "interrupted":
      return "任务已暂停，已完成的内容仍然保留。";
    case "cancelled":
      return "任务已取消，取消前完成的内容仍然保留。";
    default:
      if (execution.traceHealth !== "complete") {
        return "任务已经完成，但部分诊断信息不完整。";
      }
      if (execution.displayName === "题库整理") {
        return "资料整理已经完成，可以查看生成结果。";
      }
      if (execution.displayName === "复习助手") {
        return "本轮复习已经完成，结果已保存。";
      }
      if (execution.displayName === "深入讨论") {
        return "讨论已经完成，可以回看结论与过程。";
      }
      if (execution.displayName === "画像助手") {
        return "画像处理已经完成，相关建议已保存。";
      }
      if (execution.displayName === "项目深挖") {
        return "项目分析已经完成，可以查看问题与回答思路。";
      }
      return "任务已经完成，结果已保存。";
  }
}

export function executionNeedsAction(execution: ExecutionSummary) {
  return [
    "queued",
    "waiting_for_input",
    "waiting_for_approval",
    "partial_success",
    "failed",
  ].includes(execution.status);
}

export function formatRunUpdatedAt(value: string) {
  const date = parseApiTimestamp(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const dayKey = (target: Date) => new Intl.DateTimeFormat("en-CA", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(target);
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const time = formatBeijingTime(value, false) ?? "—";
  if (dayKey(date) === dayKey(now)) return `今天 ${time}`;
  if (dayKey(date) === dayKey(yesterday)) return `昨天 ${time}`;
  return formatBeijingDateTime(value) ?? "时间未知";
}

function StatusIcon({ status }: { status: string }) {
  if (status === "running") return <LoaderCircle size={16} aria-hidden="true" />;
  if (status === "completed") return <CheckCircle2 size={16} aria-hidden="true" />;
  if (status === "recovered") return <CheckCircle2 size={16} aria-hidden="true" />;
  if (status === "failed") return <XCircle size={16} aria-hidden="true" />;
  if (status === "partial_success") return <AlertTriangle size={16} aria-hidden="true" />;
  if (status === "interrupted") return <PauseCircle size={16} aria-hidden="true" />;
  return <Clock3 size={16} aria-hidden="true" />;
}

interface ExecutionListProps {
  executions: ExecutionSummary[];
  currentExecutionBySession: ReadonlyMap<string, ExecutionSummary>;
  executionHistoryBySession: ReadonlyMap<string, ExecutionSummary[]>;
  selectedId: string | null;
  onSelect: (executionId: string) => void;
  returnTo: string;
}

export function ExecutionList({
  executions,
  currentExecutionBySession,
  executionHistoryBySession,
  selectedId,
  onSelect,
  returnTo,
}: ExecutionListProps) {
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  return (
    <div className="execution-list" aria-label="Execution 列表">
      <div className="execution-list__header" aria-hidden="true">
        <span>任务</span>
        <span>运行状态</span>
        <span>结果摘要</span>
        <span>最近更新</span>
      </div>
      {executions.map((execution) => {
        const executionHistory = executionHistoryBySession.get(execution.sessionId)
          ?? [execution];
        const executionCount = executionHistory.length;
        const historyExpanded = expandedSessionId === execution.sessionId;
        const currentSessionExecution =
          currentExecutionBySession.get(execution.sessionId) ?? execution;
        const isHistorical =
          currentSessionExecution.id !== execution.id;
        const isHistoricalProblem = isHistorical
          && ["failed", "partial_success"].includes(execution.status);
        const sessionRecovered = isHistoricalProblem
          && !["failed", "partial_success"].includes(currentSessionExecution.status);
        const displayStatus = sessionRecovered
          ? "recovered"
          : isHistoricalProblem
            ? execution.status === "failed"
              ? "historical_failed"
              : "historical_partial"
            : execution.status;
        const resultSummary = sessionRecovered
          ? `这次运行曾出现问题；会话后续已更新，当前为“${statusLabel(currentSessionExecution.status)}”。`
          : isHistoricalProblem
            ? "这是较早的一次异常记录，请以同一会话的最新状态为准。"
            : executionResultSummary(execution);
        return (
        <div className="execution-row-card" key={execution.id}>
          <div className="execution-row-card__main">
            <button
              className="execution-row"
              data-status={displayStatus}
              aria-pressed={execution.id === selectedId}
              type="button"
              onClick={() => onSelect(execution.id)}
            >
              <span className="execution-row__identity">
                <span className="execution-row__icon" aria-hidden="true">
                  <Bot size={17} />
                </span>
                <span>
                  <strong>{executionTaskTitle(execution)}</strong>
                  <small>{execution.displayName}</small>
                </span>
              </span>
              <span className="execution-status" data-status={displayStatus}>
                <StatusIcon status={displayStatus} />
                {statusLabel(displayStatus)}
              </span>
              <span className="execution-row__summary">
                {resultSummary}
              </span>
              <time dateTime={execution.finishedAt ?? execution.startedAt ?? execution.createdAt}>
                {formatRunUpdatedAt(
                  execution.finishedAt ?? execution.startedAt ?? execution.createdAt,
                )}
              </time>
            </button>
            {executionCount > 1 ? (
              <button
                className="execution-row__history-toggle"
                type="button"
                aria-expanded={historyExpanded}
                aria-controls={`execution-history-${execution.sessionId}`}
                onClick={() => setExpandedSessionId(
                  historyExpanded ? null : execution.sessionId,
                )}
              >
                <History size={14} aria-hidden="true" />
                {historyExpanded ? "收起运行记录" : `查看 ${executionCount} 次运行`}
                <ChevronDown size={14} aria-hidden="true" />
              </button>
            ) : null}
            <Link
              className="execution-row__details"
              to={`/agents/executions/${encodeURIComponent(execution.id)}`}
              state={{ from: returnTo }}
              aria-label={`查看“${execution.title}”运行详情`}
            >
              详情
            </Link>
          </div>
          {historyExpanded ? (
            <section
              className="execution-history"
              id={`execution-history-${execution.sessionId}`}
              aria-label={`${executionTaskTitle(execution)}的运行记录`}
            >
              <header>
                <strong>运行记录</strong>
                <span>共 {executionCount} 次，最近一次在最前</span>
              </header>
              <ol>
                {executionHistory.map((historyExecution, index) => {
                  const runNumber = executionCount - index;
                  const isCurrent = historyExecution.id === currentSessionExecution.id;
                  const recoveredFailure = !isCurrent
                    && ["failed", "partial_success"].includes(historyExecution.status)
                    && !["failed", "partial_success"].includes(currentSessionExecution.status);
                  return (
                    <li key={historyExecution.id}>
                      <span className="execution-history__ordinal">
                        第 {runNumber} 次
                        {isCurrent ? <em>当前运行</em> : null}
                      </span>
                      <span
                        className="execution-status"
                        data-status={recoveredFailure ? "recovered" : historyExecution.status}
                      >
                        <StatusIcon status={recoveredFailure ? "recovered" : historyExecution.status} />
                        {recoveredFailure
                          ? "历史失败·已恢复"
                          : statusLabel(historyExecution.status)}
                      </span>
                      <time dateTime={historyExecution.finishedAt ?? historyExecution.startedAt ?? historyExecution.createdAt}>
                        {formatRunUpdatedAt(
                          historyExecution.finishedAt
                          ?? historyExecution.startedAt
                          ?? historyExecution.createdAt,
                        )}
                      </time>
                      <span>{executionResultSummary(historyExecution)}</span>
                      <Link
                        to={`/agents/executions/${encodeURIComponent(historyExecution.id)}`}
                        state={{ from: returnTo }}
                        aria-label={`查看第 ${runNumber} 次运行详情`}
                      >
                        查看 Trace
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}
        </div>
        );
      })}
    </div>
  );
}
