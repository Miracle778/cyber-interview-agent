import { Activity, CircleCheck, Clock3, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { CurationSession } from "./reviewTypes";

const stageLabels: Record<string, string> = {
  queued: "等待运行", reading_sources: "读取资料", generating: "生成候选题", merging: "相似题合并", summarizing: "生成总结", waiting_for_command: "等待确认", publishing: "发布题目", completed: "已完成", failed: "运行失败",
};

function elapsedLabel(startedAt: string | null | undefined, finishedAt: string | null | undefined) {
  if (!startedAt) return "尚未开始";
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "计算中";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function CurationRuntimePanel({ session, retrying = false, onRetry = () => undefined }: { session: CurationSession | null; retrying?: boolean; onRetry?: () => void }) {
  const total = session?.progress.total ?? 0;
  const percentage = total > 0 ? Math.min(100, Math.round(((session?.progress.completed ?? 0) / total) * 100)) : 0;
  const stages = session?.messages.filter((message) => message.messageKind === "stage").slice(-6) ?? [];
  return (
    <aside className="curation-runtime-panel" aria-label="整理运行状态">
      <div className="review-pane-title"><Activity size={17} /><strong>运行状态</strong></div>
      {!session ? <p className="status-note">选择会话后查看运行阶段、题目状态和 Token 用量。</p> : <>
        <div className="curation-stage"><span className={`curation-stage__icon curation-stage__icon--${session.stage}`}>{session.stage === "failed" ? <TriangleAlert size={18} /> : session.stage === "completed" ? <CircleCheck size={18} /> : <Clock3 size={18} />}</span><div><small>当前阶段</small><strong>{stageLabels[session.stage] ?? session.stage}</strong></div></div>
        <div className="review-progress" aria-label={`整理进度 ${percentage}%`}><span style={{ width: `${percentage}%` }} /></div>
        <p className="curation-progress-copy">{session.progress.completed} / {session.progress.total} 个处理单元</p>
        <div className="curation-stats">
          <div className="curation-stat"><span className="curation-stat__value">{session.candidateCount}</span><span className="curation-stat__label">候选题</span></div>
          <div className="curation-stat"><span className="curation-stat__value">{session.pendingCount}</span><span className="curation-stat__label">待确认</span></div>
          <div className="curation-stat"><span className="curation-stat__value">{session.publishedCount}</span><span className="curation-stat__label">已发布</span></div>
          <div className="curation-stat"><span className="curation-stat__value">{session.usage.callCount}</span><span className="curation-stat__label">调用次数</span></div>
        </div>
        <div className="curation-usage">{session.usage.totalTokens.toLocaleString()} tokens · 执行 {session.executionStatus ?? "尚未启动"}</div>
        <dl className="curation-runtime-facts">
          <div><dt>耗时</dt><dd>{elapsedLabel(session.executionStartedAt, session.executionFinishedAt)}</dd></div>
          <div><dt>上下文</dt><dd>{session.contextCompacted ? "已压缩" : "未触发压缩"}</dd></div>
        </dl>
        {stages.length > 0 ? <section className="curation-stage-history" aria-label="执行过程"><strong>执行过程</strong><ol>{stages.map((message) => <li key={message.id}><span /> <div><p>{message.content}</p><time>{message.createdAt}</time></div></li>)}</ol></section> : null}
        {session.stage === "failed" ? <section className="curation-retry" role="alert"><TriangleAlert size={17} /><div><strong>Agent 执行失败</strong><p>{session.executionErrorMessage ?? session.executionErrorCode ?? "可以保留当前会话并重新执行。"}</p>{session.executionErrorCode ? <code>{session.executionErrorCode}</code> : null}</div><Button size="sm" loading={retrying} onClick={onRetry}><RefreshCw size={15} />重试整理</Button></section> : null}
        {session.contextCompacted ? <div className="curation-context-note"><Sparkles size={15} />较早对话已压缩为摘要，后续重写会继续使用当前会话上下文。</div> : null}
        {session.warnings.length > 0 ? <div className="curation-runtime-warning"><TriangleAlert size={16} /><span>包含重复或正在整理的资料，题匠会保留来源并合并相似题。</span></div> : null}
      </>}
    </aside>
  );
}
