import { Activity, ChevronDown, CircleCheck, Clock3, RefreshCw, TriangleAlert } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { CurationSession } from "./reviewTypes";

const stageLabels: Record<string, string> = {
  queued: "等待运行", reading_sources: "读取资料", generating: "生成候选题", merging: "相似题合并", summarizing: "生成总结", waiting_for_command: "等待确认", publishing: "发布题目", completed: "已完成", failed: "运行失败",
};

function tokenLabel(value: number) {
  const precision = value >= 100_000 ? 1 : 2;
  return `${(value / 1000).toFixed(precision).replace(/\.0+$|(?<=\.[0-9])0+$/, "")}k`;
}

export function CurationRuntimePanel({ session, retrying = false, onRetry = () => undefined }: { session: CurationSession | null; retrying?: boolean; onRetry?: () => void }) {
  const [runtimeOpen, setRuntimeOpen] = useState(true);
  const [warningsOpen, setWarningsOpen] = useState(true);
  const total = session?.progress.total ?? 0;
  const percentage = total > 0 ? Math.min(100, Math.round(((session?.progress.completed ?? 0) / total) * 100)) : 0;
  const currentContextTokens = session?.contextUsage?.currentTokens ?? 0;
  const contextThresholdTokens = session?.contextUsage?.thresholdTokens ?? 0;
  const contextPercentage = contextThresholdTokens > 0 ? Math.min(100, Math.round((currentContextTokens / contextThresholdTokens) * 100)) : 0;
  return (
    <aside className="curation-runtime-panel" aria-label="整理运行状态">
      <div className="review-pane-title curation-runtime-title"><Activity size={17} /><strong>运行状态</strong>{session ? <span className={`curation-runtime-badge curation-runtime-badge--${session.stage}`}>{stageLabels[session.stage] ?? session.stage}</span> : null}</div>
      {!session ? <p className="status-note">选择会话后查看运行阶段、题目状态和 Token 用量。</p> : <>
        <section className="curation-runtime-overview" aria-label="整理状态概览">
          <div className="curation-runtime-stage"><span className={`curation-stage__icon curation-stage__icon--${session.stage}`}>{session.stage === "failed" ? <TriangleAlert size={18} /> : session.stage === "completed" ? <CircleCheck size={18} /> : <Clock3 size={18} />}</span><div><small>当前任务</small><strong>{stageLabels[session.stage] ?? session.stage}</strong></div></div>
          <div className="curation-runtime-progress-meta"><span>整体进度</span><strong>{percentage}%</strong></div>
          <div className="review-progress" aria-label={`整理进度 ${percentage}%`}><span style={{ width: `${percentage}%` }} /></div>
          <small className="curation-runtime-units">{session.progress.completed} / {session.progress.total} 个处理单元</small>
        </section>
        <div className="curation-runtime-metrics" aria-label="题目统计">
          <div><strong>{session.candidateCount}</strong><span>候选题</span></div>
          <div><strong>{session.pendingCount}</strong><span>待确认</span></div>
          <div><strong>{session.publishedCount}</strong><span>已发布</span></div>
        </div>
        {session.stage === "failed" ? <section className="curation-retry" role="alert"><TriangleAlert size={17} /><div><strong>Agent 执行失败</strong><p>{session.executionErrorMessage ?? session.executionErrorCode ?? "可以保留当前会话并重新执行。"}</p>{session.executionErrorCode ? <code>{session.executionErrorCode}</code> : null}</div><Button size="sm" loading={retrying} onClick={onRetry}><RefreshCw size={15} />重试整理</Button></section> : null}
        <details className="curation-runtime-disclosure" open={runtimeOpen}><summary onClick={(event) => { event.preventDefault(); setRuntimeOpen((current) => !current); }}><span><Activity size={16} />运行详情</span><small>{session.usage.callCount} 次调用</small><ChevronDown size={16} /></summary><div className="curation-runtime-disclosure__body"><dl><div><dt>执行状态</dt><dd>{session.executionStatus ?? "尚未启动"}</dd></div><div><dt>Token</dt><dd>{tokenLabel(session.usage.totalTokens)}</dd></div></dl><div className="curation-context-compact"><div className="curation-context-ring" style={{ "--context-progress": `${contextPercentage * 3.6}deg` } as CSSProperties}><span>{contextPercentage}%</span></div><div><small>当前上下文 / 压缩阈值</small><strong>{tokenLabel(currentContextTokens)} / {contextThresholdTokens > 0 ? tokenLabel(contextThresholdTokens) : "—"}</strong></div></div></div></details>
        {session.warnings.length > 0 ? <details className="curation-runtime-warning" open={warningsOpen}><summary onClick={(event) => { event.preventDefault(); setWarningsOpen((current) => !current); }}><TriangleAlert size={16} />提示 <span>{session.warnings.length}</span></summary><p>包含重复或正在整理的资料。题匠会保留全部来源，并在候选生成后合并高置信相似题。</p></details> : null}
      </>}
    </aside>
  );
}
