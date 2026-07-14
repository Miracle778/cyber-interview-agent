import { Activity, CircleCheck, Clock3, TriangleAlert } from "lucide-react";
import type { CurationSession } from "./reviewTypes";

const stageLabels: Record<string, string> = {
  queued: "等待运行", reading_sources: "读取资料", generating: "生成候选题", merging: "相似题合并", summarizing: "生成总结", waiting_for_command: "等待确认", publishing: "发布题目", completed: "已完成", failed: "运行失败",
};

export function CurationRuntimePanel({ session }: { session: CurationSession | null }) {
  const total = session?.progress.total ?? 0;
  const percentage = total > 0 ? Math.min(100, Math.round(((session?.progress.completed ?? 0) / total) * 100)) : 0;
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
        {session.warnings.length > 0 ? <div className="curation-runtime-warning"><TriangleAlert size={16} /><span>包含重复或正在整理的资料，题匠会保留来源并合并相似题。</span></div> : null}
      </>}
    </aside>
  );
}
