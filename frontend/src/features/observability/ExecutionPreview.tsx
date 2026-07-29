import { AlertTriangle, ArrowUpRight, Bot, Clock3, Cpu, Database, X } from "lucide-react";
import type { ExecutionSummary } from "./observabilityTypes";
import {
  formatCompactNumber,
  formatDuration,
  statusLabel,
} from "./ExecutionList";


interface ExecutionPreviewProps {
  execution: ExecutionSummary | null;
  onClose: () => void;
}

export function ExecutionPreview({
  execution,
  onClose,
}: ExecutionPreviewProps) {
  return (
    <aside className="execution-preview" aria-label="本次运行">
      <header>
        <strong>本次运行</strong>
        <button type="button" aria-label="关闭运行预览" onClick={onClose}>
          <X size={17} aria-hidden="true" />
        </button>
      </header>
      {execution ? (
        <>
          <div className="execution-preview__identity">
            <span aria-hidden="true"><Bot size={19} /></span>
            <div>
              <strong>{execution.title}</strong>
              <small>{execution.displayName} · {statusLabel(execution.status)}</small>
            </div>
          </div>
          {execution.traceHealth !== "complete" ? (
            <p className="execution-preview__warning">
              <AlertTriangle size={16} aria-hidden="true" />
              {execution.traceHealth === "missing"
                ? "本次运行缺少高级诊断记录"
                : "本次运行的诊断记录不完整"}
            </p>
          ) : null}
          <dl className="execution-preview__metrics">
            <div><dt><Clock3 size={15} />耗时</dt><dd>{formatDuration(execution.latencyMs)}</dd></div>
            <div><dt><Cpu size={15} />模型调用</dt><dd>{execution.modelCallCount}</dd></div>
            <div><dt><Database size={15} />Token</dt><dd>{formatCompactNumber(execution.totalTokens)}</dd></div>
            <div><dt>上下文</dt><dd>{formatCompactNumber(execution.contextCurrentTokens)} / {formatCompactNumber(execution.contextThresholdTokens)}</dd></div>
          </dl>
          <div className="execution-preview__actions">
            {execution.capabilities.includes("open_business") && execution.route ? (
              <a href={execution.route}>
                打开业务页面
                <ArrowUpRight size={15} aria-hidden="true" />
              </a>
            ) : null}
          </div>
        </>
      ) : (
        <p className="execution-preview__empty">选择一条运行查看摘要。</p>
      )}
    </aside>
  );
}
