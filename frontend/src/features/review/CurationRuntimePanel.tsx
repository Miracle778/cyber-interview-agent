import { Activity, ArrowLeft, ChevronDown, FileText, RefreshCw, TriangleAlert } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { CurationArtifactCard } from "./CurationArtifactCard";
import type { CurationSession, QuestionCandidate } from "./reviewTypes";

const candidateStatusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已发布",
  rejected: "待修改",
};

function tokenLabel(value: number) {
  const precision = value >= 100_000 ? 1 : 2;
  return `${(value / 1000).toFixed(precision).replace(/\.0+$|(?<=\.[0-9])0+$/, "")}k`;
}

type CandidateStatus = QuestionCandidate["status"];

interface CurationRuntimePanelProps {
  session: CurationSession | null;
  candidates?: QuestionCandidate[] | null;
  activeModelLabel?: string;
  retrying?: boolean;
  artifactBusyId?: string | null;
  statusFilter?: CandidateStatus | null;
  onStatusFilterChange?: (status: CandidateStatus | null) => void;
  onOpenCandidate?: (candidateId: string) => void;
  onPublishCandidate?: (candidateId: string) => void;
  onSaveNote?: (candidateId: string, note: string) => void;
  onRetry?: () => void;
}

const statusOrder: CandidateStatus[] = ["review_pending", "published", "rejected", "draft"];

export function CurationRuntimePanel({ session, candidates = null, activeModelLabel = "", retrying = false, artifactBusyId = null, statusFilter = null, onStatusFilterChange = () => undefined, onOpenCandidate = () => undefined, onPublishCandidate = () => undefined, onSaveNote = () => undefined, onRetry = () => undefined }: CurationRuntimePanelProps) {
  const [runtimeOpen, setRuntimeOpen] = useState(true);
  const [warningsOpen, setWarningsOpen] = useState(true);
  const currentContextTokens = session?.contextUsage?.currentTokens ?? 0;
  const contextThresholdTokens = session?.contextUsage?.thresholdTokens ?? 0;
  const contextPercentage = contextThresholdTokens > 0 ? Math.min(100, Math.round((currentContextTokens / contextThresholdTokens) * 100)) : 0;
  const candidateItems = candidates ?? [];
  const statusCounts = candidateItems.reduce((counts, candidate) => ({ ...counts, [candidate.status]: counts[candidate.status] + 1 }), { draft: 0, review_pending: 0, published: 0, rejected: 0 });
  const ordinalByCandidate = new Map(session?.summary.items.map((item) => [item.candidateId, item.ordinal]) ?? []);
  const summaryCandidateIds = new Set(session?.summary.items.map((item) => item.candidateId) ?? []);
  const recentCandidate = [...candidateItems].sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))[0] ?? null;
  const filteredCandidates = statusFilter ? candidateItems
    .filter((candidate) => candidate.status === statusFilter)
    .sort((left, right) => (ordinalByCandidate.get(left.id) ?? Number.MAX_SAFE_INTEGER) - (ordinalByCandidate.get(right.id) ?? Number.MAX_SAFE_INTEGER) || Date.parse(right.updatedAt) - Date.parse(left.updatedAt)) : [];
  const generationLabel = session?.progress?.phase === "discovery" ? "正在识别题目" : session?.progress?.phase === "enrichment" ? "正在补全候选" : null;
  const candidateLimitReached = session?.warnings?.some((warning) => warning.code === "candidate_limit_reached") ?? false;
  return (
    <aside className="curation-runtime-panel" aria-label="整理运行状态">
      <div className="review-pane-title curation-runtime-title">{statusFilter ? <button type="button" className="curation-runtime-back" aria-label="返回运行状态" onClick={() => onStatusFilterChange(null)}><ArrowLeft size={17} /></button> : <FileText size={17} />}<strong>{statusFilter ? `${candidateStatusLabels[statusFilter]}候选题` : "候选状态"}</strong>{session ? <span className="curation-runtime-badge">{statusFilter ? `${filteredCandidates.length} 个文件` : `${candidateItems.length} 道`}</span> : null}</div>
      {!session ? <p className="status-note">选择会话后查看运行阶段、题目状态和 Token 用量。</p> : <>
        <section className="curation-candidate-status" aria-label="候选题实时状态" aria-live="polite">
          {statusFilter ? null : <header><div><strong>候选题</strong><small>最近变动随操作实时更新</small></div><span>{candidateItems.length} 道</span></header>}
          <div className="curation-candidate-status__metrics">
            {statusOrder.map((status) => <button key={status} type="button" aria-pressed={statusFilter === status} onClick={() => onStatusFilterChange(statusFilter === status ? null : status)}><strong>{statusCounts[status]}</strong><span>{candidateStatusLabels[status]}</span></button>)}
          </div>
          {statusFilter ? <div className="curation-candidate-status__files" role="list" aria-label={`${candidateStatusLabels[statusFilter]}文件`}>
            {filteredCandidates.length === 0 ? <p className="curation-candidate-status__empty">当前没有{candidateStatusLabels[statusFilter]}文件。</p> : filteredCandidates.map((candidate) => <CurationArtifactCard key={candidate.id} candidate={candidate} compact historical={!summaryCandidateIds.has(candidate.id)} busy={artifactBusyId === candidate.id} onOpen={onOpenCandidate} onPublish={onPublishCandidate} onSaveNote={onSaveNote} />)}
          </div> : candidates === null ? <p className="curation-candidate-status__empty">正在同步候选题…</p> : recentCandidate === null ? <p className="curation-candidate-status__empty">候选题生成后会在这里显示。</p> : <div className="curation-candidate-status__recent"><small>最近更新</small><div><span>{ordinalByCandidate.get(recentCandidate.id) ?? "旧"}</span><strong title={recentCandidate.question.title}>{recentCandidate.question.title}</strong><em className={`candidate-status candidate-status--${recentCandidate.status}`}>{candidateStatusLabels[recentCandidate.status]}</em></div></div>}
        </section>
        {statusFilter ? null : <>
        {session.stage === "failed" ? <section className="curation-retry" role="alert"><TriangleAlert size={17} /><div><strong>Agent 执行失败</strong><p>{session.executionErrorMessage ?? session.executionErrorCode ?? "可以保留当前会话并重新执行。"}</p>{session.executionErrorCode ? <code>{session.executionErrorCode}</code> : null}</div><Button size="sm" loading={retrying} onClick={onRetry}><RefreshCw size={15} />重试整理</Button></section> : null}
        {session.stage === "generating" && generationLabel ? <section className="curation-progress" role="status" aria-live="polite" aria-atomic="true"><Activity size={17} /><div><strong>{generationLabel}</strong><p>{session.progress?.completed ?? 0} / {session.progress?.total ?? 0}</p></div></section> : null}
        <details className="curation-runtime-disclosure" open={runtimeOpen}><summary onClick={(event) => { event.preventDefault(); setRuntimeOpen((current) => !current); }}><span><Activity size={16} />运行详情</span><small>{session.usage.callCount} 次调用</small><ChevronDown size={16} /></summary><div className="curation-runtime-disclosure__body"><dl><div><dt>执行状态</dt><dd>{session.executionStatus ?? "尚未启动"}</dd></div>{activeModelLabel ? <div><dt>执行模型</dt><dd title={activeModelLabel}>{activeModelLabel}</dd></div> : null}<div><dt>Token</dt><dd>{tokenLabel(session.usage.totalTokens)}</dd></div></dl><div className="curation-context-compact"><div className="curation-context-ring" style={{ "--context-progress": `${contextPercentage * 3.6}deg` } as CSSProperties}><span>{contextPercentage}%</span></div><div><small>当前上下文 / 压缩阈值</small><strong>{tokenLabel(currentContextTokens)} / {contextThresholdTokens > 0 ? tokenLabel(contextThresholdTokens) : "—"}</strong></div></div></div></details>
        {(session.warnings?.length ?? 0) > 0 ? <details className="curation-runtime-warning" open={warningsOpen}><summary onClick={(event) => { event.preventDefault(); setWarningsOpen((current) => !current); }}><TriangleAlert size={16} />提示 <span>{session.warnings?.length ?? 0}</span></summary><p>{candidateLimitReached ? "已生成前 200 道候选题，请先审核当前结果" : "包含重复或正在整理的资料。题匠会保留全部来源，并在候选生成后合并高置信相似题。"}</p></details> : null}
        </>}
      </>}
    </aside>
  );
}
