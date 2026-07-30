import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Cpu,
  Database,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { ExecutionSummary } from "./observabilityTypes";
import {
  executionNeedsAction,
  executionResultSummary,
  executionTaskTitle,
  formatCompactNumber,
  formatDuration,
  formatRunUpdatedAt,
  statusLabel,
} from "./ExecutionList";
import { executionBusinessDestination } from "./observabilityNavigation";


interface ExecutionPreviewProps {
  execution: ExecutionSummary | null;
  onClose: () => void;
  returnTo: string;
}

function nextStepCopy(execution: ExecutionSummary) {
  if (execution.status === "waiting_for_input") {
    return "回到原任务补充信息，Agent 会从当前步骤继续。";
  }
  if (execution.status === "waiting_for_approval") {
    return "检查已经准备好的结果，确认后任务才会继续。";
  }
  if (["failed", "partial_success"].includes(execution.status)) {
    return "先查看失败原因和已保留结果，再决定是否继续处理。";
  }
  if (execution.status === "running") {
    return "无需停留在这里；任务完成后，状态和结果会自动更新。";
  }
  if (execution.capabilities.includes("manual_judge")) {
    return "如需进一步确认结果质量，可以进入运行质量页面检查。";
  }
  return "可以回到原业务页面查看本次任务生成或更新的内容。";
}

function primaryActionLabel(execution: ExecutionSummary) {
  if (["waiting_for_input", "waiting_for_approval"].includes(execution.status)) {
    return "继续处理";
  }
  if (["failed", "partial_success"].includes(execution.status)) {
    return "查看并处理";
  }
  if (execution.status === "running") return "查看任务页面";
  return "查看结果";
}

export function ExecutionPreview({
  execution,
  onClose,
  returnTo,
}: ExecutionPreviewProps) {
  const businessDestination = execution
    ? executionBusinessDestination(execution, returnTo)
    : null;
  const hasBusinessDestination = Boolean(
    execution?.capabilities.includes("open_business")
    && businessDestination?.to,
  );
  const runDetailLabel = execution
    && ["failed", "partial_success"].includes(execution.status)
    ? "查看失败详情"
    : "查看运行详情";
  return (
    <aside className="execution-preview" aria-label="任务详情">
      <header>
        <div>
          <strong>任务详情</strong>
          <small>查看结果与下一步</small>
        </div>
        <button type="button" aria-label="关闭任务详情" onClick={onClose}>
          <X size={17} aria-hidden="true" />
        </button>
      </header>
      {execution ? (
        <div className="execution-preview__body">
          <div className="execution-preview__identity">
            <span aria-hidden="true"><Bot size={19} /></span>
            <div>
              <strong>{executionTaskTitle(execution)}</strong>
              <small>
                {execution.displayName} · {formatRunUpdatedAt(
                  execution.finishedAt ?? execution.startedAt ?? execution.createdAt,
                )}
              </small>
            </div>
          </div>

          <section className="execution-preview__outcome">
            <span
              data-tone={executionNeedsAction(execution) ? "attention" : "success"}
              aria-hidden="true"
            >
              {executionNeedsAction(execution)
                ? <CircleAlert size={21} />
                : <CheckCircle2 size={21} />}
            </span>
            <div>
              <small>当前情况</small>
              <h3>{statusLabel(execution.status)}</h3>
              <p>{executionResultSummary(execution)}</p>
            </div>
          </section>

          {execution.traceHealth !== "complete" ? (
            <p className="execution-preview__warning">
              <AlertTriangle size={16} aria-hidden="true" />
              {execution.traceHealth === "missing"
                ? "任务结果不受影响，但本次运行缺少高级诊断记录。"
                : "任务结果不受影响，但本次运行的诊断记录不完整。"}
            </p>
          ) : null}

          <section className="execution-preview__results">
            <h3>本次运行</h3>
            <ul>
              <li><Check size={15} aria-hidden="true" />运行状态已记录并同步</li>
              <li><Check size={15} aria-hidden="true" />完成 {execution.modelCallCount} 次模型处理</li>
              <li>
                <Check size={15} aria-hidden="true" />
                {execution.systemOperationCount > 0
                  ? `包含 ${execution.systemOperationCount} 个内部处理步骤`
                  : "没有额外的内部处理步骤"}
              </li>
            </ul>
          </section>

          <section className="execution-preview__next">
            <span aria-hidden="true"><ArrowRight size={18} /></span>
            <div>
              <h3>接下来可以这样做</h3>
              <p>{nextStepCopy(execution)}</p>
            </div>
          </section>

          <div className="execution-preview__actions">
            {hasBusinessDestination ? (
              <Link
                className="execution-preview__primary"
                to={businessDestination!.to}
                state={{ from: returnTo }}
              >
                {businessDestination!.exact
                  ? primaryActionLabel(execution)
                  : "打开业务页面"}
                <ArrowUpRight size={15} aria-hidden="true" />
              </Link>
            ) : (
              <Link
                className="execution-preview__primary"
                to={`/agents/executions/${encodeURIComponent(execution.id)}`}
                state={{ from: returnTo }}
              >
                {runDetailLabel}
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            )}
            {hasBusinessDestination ? (
              <Link
                className="execution-preview__secondary execution-preview__run-detail"
                to={`/agents/executions/${encodeURIComponent(execution.id)}`}
                state={{ from: returnTo }}
              >
                {runDetailLabel}
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            ) : null}
            {execution.capabilities.includes("manual_judge") ? (
              <Link
                className="execution-preview__secondary"
                to={`/agents/evaluations?executionId=${encodeURIComponent(execution.id)}`}
              >
                检查运行质量
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            ) : null}
          </div>

          <details className="execution-preview__technical">
            <summary>
              <span>查看技术详情</span>
              <ChevronRight size={16} aria-hidden="true" />
            </summary>
            <dl className="execution-preview__metrics">
              <div><dt><Clock3 size={15} />耗时</dt><dd>{formatDuration(execution.latencyMs)}</dd></div>
              <div><dt><Cpu size={15} />模型调用</dt><dd>{execution.modelCallCount}</dd></div>
              <div><dt><Database size={15} />Token</dt><dd>{formatCompactNumber(execution.totalTokens)}</dd></div>
              <div><dt>上下文</dt><dd>{formatCompactNumber(execution.contextCurrentTokens)} / {formatCompactNumber(execution.contextThresholdTokens)}</dd></div>
              {execution.errorCode ? (
                <div><dt>错误标识</dt><dd>{execution.errorCode}</dd></div>
              ) : null}
            </dl>
          </details>
        </div>
      ) : (
        <p className="execution-preview__empty">选择一条任务查看摘要。</p>
      )}
    </aside>
  );
}
