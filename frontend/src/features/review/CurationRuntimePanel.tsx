import { Activity, ArrowLeft, Ban, ChevronDown, CirclePause, Clock3, FileText, Pause, Play, ShieldAlert, TriangleAlert, WifiOff } from "lucide-react";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { parseApiTimestamp } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { CurationArtifactCard } from "./CurationArtifactCard";
import { CurationProvisionalList } from "./CurationProvisionalList";
import type { CurationProvisionalCandidate, CurationSession, QuestionCandidate } from "./reviewTypes";

export type CurationQualityFilter = "ai_primary" | "insufficient_support" | "needs_review";

const candidateStatusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已发布",
  rejected: "待修改",
};

const executionStatusLabels: Record<string, string> = {
  queued: "等待开始",
  running: "正在处理",
  waiting_for_input: "等待输入",
  waiting_for_approval: "等待确认",
  interrupted: "已中断",
  completed: "已完成",
  failed: "处理失败",
  cancelled: "已停止",
};

function failureMessage(code?: string | null, message?: string | null) {
  if (code === "curation_work_item_failed") return "部分资料没有生成有效结果。已有进度已保存，可以继续整理或单独重试问题项。";
  if (code === "provider_timeout") return "模型响应超时。已有进度已保存，稍后继续即可。";
  if (code === "rate_limited") return "模型服务当前较忙。已有进度已保存，稍后继续即可。";
  if (code === "network_error") return "连接模型服务时中断。请检查网络后继续整理。";
  if (message && !/^[a-z0-9_.-]+$/i.test(message)) return message;
  return "这次整理没有完成。已有进度已保存，可以继续整理。";
}

function tokenLabel(value: number) {
  const precision = value >= 100_000 ? 1 : 2;
  return `${(value / 1000).toFixed(precision).replace(/\.0+$|(?<=\.[0-9])0+$/, "")}k`;
}

type CandidateStatus = QuestionCandidate["status"];

interface CurationRuntimePanelProps {
  session: CurationSession | null;
  candidates?: QuestionCandidate[] | null;
  activeModelLabel?: string;
  controlPending?: "pause" | "resume" | "terminate" | null;
  controlNotice?: string | null;
  artifactBusyId?: string | null;
  statusFilter?: CandidateStatus | null;
  qualityFilter?: CurationQualityFilter | null;
  onStatusFilterChange?: (status: CandidateStatus | null) => void;
  onQualityFilterChange?: (filter: CurationQualityFilter | null) => void;
  onOpenCandidate?: (candidateId: string) => void;
  onPublishCandidate?: (candidateId: string) => void;
  onSaveNote?: (candidateId: string, note: string) => void;
  onPause?: () => void;
  onResume?: () => void;
  onTerminate?: () => void;
  retryingSeedIds?: ReadonlySet<string>;
  onRetrySeed?: (item: CurationProvisionalCandidate) => void;
}

const statusOrder: CandidateStatus[] = ["review_pending", "published", "rejected", "draft"];

function elapsedLabel(prefix: string, elapsedMs: number) {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${prefix} ${minutes} 分 ${seconds} 秒` : `${prefix} ${seconds} 秒`;
}

interface ElapsedClockSnapshot {
  batchKey: string;
  executionKey: string;
  serverCurrentElapsed: number;
  serverCumulativeElapsed: number;
  observedAt: number;
  currentBase: number;
  cumulativeBase: number;
  running: boolean;
}

function currentMonotonicTime() {
  return globalThis.performance?.now() ?? 0;
}

export function CurationRuntimePanel({ session, candidates = null, activeModelLabel = "", controlPending = null, controlNotice = null, artifactBusyId = null, statusFilter = null, qualityFilter = null, onStatusFilterChange = () => undefined, onQualityFilterChange = () => undefined, onOpenCandidate = () => undefined, onPublishCandidate = () => undefined, onSaveNote = () => undefined, onPause = () => undefined, onResume = () => undefined, onTerminate = () => undefined, retryingSeedIds = new Set(), onRetrySeed = () => undefined }: CurationRuntimePanelProps) {
  const [runtimeOpen, setRuntimeOpen] = useState(true);
  const [warningsOpen, setWarningsOpen] = useState(true);
  const [, setClockTick] = useState(0);
  const elapsedClock = useRef<ElapsedClockSnapshot | null>(null);
  const batchRunning = session?.batchStatus === "generating" && session.stage !== "pausing";
  useEffect(() => {
    if (!batchRunning) return;
    const timer = globalThis.setInterval(() => setClockTick((tick) => tick + 1), 1000);
    return () => globalThis.clearInterval(timer);
  }, [batchRunning, session?.executionId]);
  const currentContextTokens = session?.contextUsage?.currentTokens ?? 0;
  const contextThresholdTokens = session?.contextUsage?.thresholdTokens ?? 0;
  const contextPercentage = contextThresholdTokens > 0 ? Math.min(100, Math.round((currentContextTokens / contextThresholdTokens) * 100)) : 0;
  const candidateItems = candidates ?? [];
  const statusCounts = candidateItems.reduce((counts, candidate) => ({ ...counts, [candidate.status]: counts[candidate.status] + 1 }), { draft: 0, review_pending: 0, published: 0, rejected: 0 });
  const ordinalByCandidate = new Map(session?.summary.items.map((item) => [item.candidateId, item.ordinal]) ?? []);
  const summaryCandidateIds = new Set(session?.summary.items.map((item) => item.candidateId) ?? []);
  const recentCandidate = [...candidateItems].sort((left, right) => parseApiTimestamp(right.updatedAt).getTime() - parseApiTimestamp(left.updatedAt).getTime())[0] ?? null;
  const qualityMatches = (candidate: QuestionCandidate) => qualityFilter === "ai_primary"
    ? ["model", "unknown"].includes(candidate.answerBasis ?? "unknown")
    : qualityFilter === "insufficient_support"
      ? ["partial", "minimal", "unknown"].includes(candidate.materialSupport ?? "unknown")
      : qualityFilter === "needs_review"
        ? candidate.needsReview !== false || (candidate.normalizationIssues?.length ?? 0) > 0
        : true;
  const filteredCandidates = statusFilter || qualityFilter ? candidateItems
    .filter((candidate) => (!statusFilter || candidate.status === statusFilter) && qualityMatches(candidate))
    .sort((left, right) => (ordinalByCandidate.get(left.id) ?? Number.MAX_SAFE_INTEGER) - (ordinalByCandidate.get(right.id) ?? Number.MAX_SAFE_INTEGER) || parseApiTimestamp(right.updatedAt).getTime() - parseApiTimestamp(left.updatedAt).getTime()) : [];
  const generationLabel = session?.progress?.phase === "discovery" ? "正在识别题目" : session?.progress?.phase === "enrichment" ? "正在补全候选" : null;
  const candidateLimitReached = session?.warnings?.some((warning) => warning.code === "candidate_limit_reached") ?? false;
  const activeFilterLabel = statusFilter ? candidateStatusLabels[statusFilter] : qualityFilter === "ai_primary" ? "主要由 AI 生成" : qualityFilter === "insufficient_support" ? "材料支持不足" : qualityFilter === "needs_review" ? "需要人工复核" : null;
  const sourceLabelById = new Map(session?.sources?.map((source) => [source.id, source.filename]) ?? []);
  const serverCurrentElapsed = session?.timing?.currentElapsedMs ?? 0;
  const serverCumulativeElapsed = session?.timing?.cumulativeElapsedMs ?? 0;
  const monotonicNow = currentMonotonicTime();
  const batchKey = session?.activeBatchId ?? session?.id ?? "none";
  const executionKey = session?.executionId ?? "none";
  const previousClock = elapsedClock.current;
  if (!previousClock || previousClock.batchKey !== batchKey) {
    elapsedClock.current = {
      batchKey,
      executionKey,
      serverCurrentElapsed,
      serverCumulativeElapsed,
      observedAt: monotonicNow,
      currentBase: serverCurrentElapsed,
      cumulativeBase: serverCumulativeElapsed,
      running: batchRunning,
    };
  } else {
    const previousDelta = previousClock.running ? Math.max(0, monotonicNow - previousClock.observedAt) : 0;
    const previousCurrent = previousClock.currentBase + previousDelta;
    const previousCumulative = previousClock.cumulativeBase + previousDelta;
    const snapshotChanged = previousClock.executionKey !== executionKey
      || previousClock.serverCurrentElapsed !== serverCurrentElapsed
      || previousClock.serverCumulativeElapsed !== serverCumulativeElapsed
      || previousClock.running !== batchRunning;
    if (snapshotChanged) {
      const executionChanged = previousClock.executionKey !== executionKey;
      elapsedClock.current = {
        batchKey,
        executionKey,
        serverCurrentElapsed,
        serverCumulativeElapsed,
        observedAt: monotonicNow,
        currentBase: !batchRunning || executionChanged ? serverCurrentElapsed : Math.max(previousCurrent, serverCurrentElapsed),
        cumulativeBase: !batchRunning ? serverCumulativeElapsed : Math.max(previousCumulative, serverCumulativeElapsed),
        running: batchRunning,
      };
    }
  }
  const activeClock = elapsedClock.current!;
  const activeDelta = activeClock.running ? Math.max(0, monotonicNow - activeClock.observedAt) : 0;
  const currentElapsed = activeClock.currentBase + activeDelta;
  const cumulativeElapsed = activeClock.cumulativeBase + activeDelta;
  const controlState = session?.stage === "pausing" ? "pausing" : session?.batchStatus;
  const seedProgress = session?.seedProgress;
  const activeSeedProgress = session?.progress?.phase === "discovery"
    ? null
    : seedProgress ?? null;
  const processedSeedCount = activeSeedProgress
    ? activeSeedProgress.completed + activeSeedProgress.degraded + activeSeedProgress.skipped
    : session?.progress?.completed ?? 0;
  const generatedSeedCount = session?.progress?.phase === "discovery"
    ? seedProgress?.total ?? 0
    : activeSeedProgress
    ? activeSeedProgress.completed + activeSeedProgress.degraded
    : session?.progress?.generatedCandidateCount ?? 0;
  const totalSeedCount = activeSeedProgress
    ? activeSeedProgress.total
    : session?.progress?.total ?? 0;
  const retryableCount = activeSeedProgress
    ? activeSeedProgress.retrying
    : session?.progress?.retryableUnits ?? session?.progress?.activeWorkers ?? 0;
  const pendingCount = activeSeedProgress
    ? activeSeedProgress.pending
    : session?.progress?.pendingUnits ?? 0;
  const skippedCount = activeSeedProgress ? activeSeedProgress.skipped : 0;
  const controlPresentation = controlState ? {
    generating: { label: generationLabel ?? "正在整理", detail: "已提交的处理单元会持续保存", icon: Activity },
    pausing: { label: "正在暂停…", detail: "正在安全停止活动工作单元", icon: Pause },
    paused: { label: "已暂停", detail: "当前进度已保存，可从这里继续", icon: CirclePause },
    failed: { label: "整理失败", detail: "已完成的工作单元不会重放", icon: TriangleAlert },
    interrupted: { label: "服务中断", detail: "任务已安全中断，可从已有进度继续", icon: WifiOff },
    terminated: { label: "已终止", detail: "这个整理任务不能继续", icon: Ban },
    review_pending: { label: "等待确认", detail: "候选已完成归并", icon: FileText },
    completed: { label: "整理完成", detail: "运行耗时已冻结", icon: FileText },
  }[controlState] : null;
  const ControlIcon = controlPresentation?.icon ?? Activity;
  const confirmTerminate = () => {
    if (globalThis.confirm("终止后将保留已有处理记录，但不能继续这个整理任务。确认终止？")) onTerminate();
  };
  return (
    <aside className="curation-runtime-panel" aria-label="整理运行状态">
      <div className="review-pane-title curation-runtime-title">{activeFilterLabel ? <button type="button" className="curation-runtime-back" aria-label="返回运行状态" onClick={() => { onStatusFilterChange(null); onQualityFilterChange(null); }}><ArrowLeft size={17} /></button> : <FileText size={17} />}<strong>{activeFilterLabel ? `${activeFilterLabel}候选题` : "候选状态"}</strong>{session ? <span className="curation-runtime-badge">{activeFilterLabel ? `${filteredCandidates.length} 个文件` : `${candidateItems.length} 道`}</span> : null}</div>
      {!session ? <p className="status-note">选择会话后查看运行阶段、题目状态和 Token 用量。</p> : <>
        {controlState && controlPresentation ? <section className={`curation-control-state curation-control-state--${controlState}`}>
          <div className="curation-control-state__heading" role="status" aria-live="polite" aria-atomic="true">
            <span><ControlIcon size={18} aria-hidden="true" /></span>
            <div><strong>{controlPresentation.label}</strong><small>{controlPresentation.detail}</small></div>
          </div>
          <div className="curation-control-state__progress" role="status" aria-label="整理进度" aria-live="polite" aria-atomic="true">
            <div><strong>{processedSeedCount} / {totalSeedCount}</strong><span>{session.progress?.phase === "discovery" ? "已完成识别" : "已处理"}</span></div>
            <div><strong>{generatedSeedCount}</strong><span>{session.progress?.phase === "discovery" ? "已发现题目" : "已生成候选"}</span></div>
            <div><strong>{retryableCount}</strong><span>{session.progress?.activeWorkers ? "正在处理" : "可继续处理"}</span></div>
            <div><strong>{skippedCount}</strong><span>已跳过</span></div>
            <div><strong>{pendingCount}</strong><span>等待处理</span></div>
          </div>
          <div className="curation-control-state__activity"><span>{session.progress?.activeWorkers ?? 0} 个工作单元运行中</span><span>已生成 {session.progress?.generatedCandidateCount ?? 0} 道候选</span></div>
          <div className="curation-control-state__timing" aria-live="off">
            <Clock3 size={16} aria-hidden="true" />
            <span>{elapsedLabel("本次运行", currentElapsed)}</span>
            <small>{elapsedLabel("累计运行", cumulativeElapsed)}</small>
          </div>
          {controlState === "pausing" || session.controls?.canPause || session.controls?.canResume || session.controls?.canTerminate ? <div className="curation-control-actions">
            {controlState === "pausing" ? <Button disabled><Pause size={16} />正在暂停…</Button> : null}
            {controlState !== "pausing" && session.controls?.canPause ? <Button disabled={controlPending !== null} loading={controlPending === "pause"} onClick={onPause}><Pause size={16} />暂停整理</Button> : null}
            {session.controls?.canResume ? <Button disabled={controlPending !== null} loading={controlPending === "resume"} onClick={onResume}><Play size={16} />继续整理</Button> : null}
            {session.controls?.canTerminate ? <Button disabled={controlPending !== null} className="curation-control-actions__terminate" variant="danger" loading={controlPending === "terminate"} onClick={confirmTerminate}><Ban size={16} />终止整理</Button> : null}
          </div> : null}
        </section> : null}
        {controlNotice ? <section className="curation-control-notice" role="status" aria-label="整理控制提示" aria-live="polite" aria-atomic="true"><TriangleAlert size={17} aria-hidden="true" /><p>{controlNotice}</p></section> : null}
        <CurationProvisionalList items={session.provisionalCandidates ?? []} retryingSeedIds={retryingSeedIds} onRetry={onRetrySeed} />
        {(session.sourceWarnings?.length ?? 0) > 0 ? <section className="curation-source-warnings" aria-label="资料读取提示"><header><TriangleAlert size={16} /><strong>资料读取提示</strong></header><ul>{session.sourceWarnings!.map((warning, index) => <li key={`${warning.sourceId}-${warning.code}-${index}`}><b>{sourceLabelById.get(warning.sourceId) ?? "所选资料"}</b><span>{warning.code === "no_extractable_text" ? "没有可识别的正文，已跳过" : warning.code === "unsupported_encoding" ? "文件编码暂不支持，已跳过" : warning.code === "low_signal" ? "有效内容较少，结果可能不完整" : "读取质量有限，请人工复核"}</span></li>)}</ul></section> : null}
        <section className="curation-candidate-status" aria-label="候选题实时状态" aria-live="polite">
          {activeFilterLabel ? null : <header><div><strong>候选题</strong><small>最近变动随操作实时更新</small></div><span>{candidateItems.length} 道</span></header>}
          <div className="curation-candidate-status__metrics">
            {statusOrder.map((status) => <button key={status} type="button" aria-pressed={statusFilter === status} onClick={() => onStatusFilterChange(statusFilter === status ? null : status)}><strong>{statusCounts[status]}</strong><span>{candidateStatusLabels[status]}</span></button>)}
          </div>
          <div className="curation-quality-filters" aria-label="候选质量筛选"><button type="button" aria-pressed={qualityFilter === "ai_primary"} onClick={() => onQualityFilterChange(qualityFilter === "ai_primary" ? null : "ai_primary")}><ShieldAlert size={14} />主要由 AI 生成 <b>{(session.qualitySummary?.model ?? 0) + (session.qualitySummary?.unknown ?? 0)}</b></button><button type="button" aria-pressed={qualityFilter === "insufficient_support"} onClick={() => onQualityFilterChange(qualityFilter === "insufficient_support" ? null : "insufficient_support")}><TriangleAlert size={14} />材料支持不足</button><button type="button" aria-pressed={qualityFilter === "needs_review"} onClick={() => onQualityFilterChange(qualityFilter === "needs_review" ? null : "needs_review")}><TriangleAlert size={14} />需要人工复核 <b>{session.qualitySummary?.needsReview ?? 0}</b></button></div>
          {activeFilterLabel ? <div className="curation-candidate-status__files" role="list" aria-label={`${activeFilterLabel}文件`}>
            {filteredCandidates.length === 0 ? <p className="curation-candidate-status__empty">当前没有{activeFilterLabel}文件。</p> : filteredCandidates.map((candidate) => <CurationArtifactCard key={candidate.id} candidate={candidate} compact historical={!summaryCandidateIds.has(candidate.id)} busy={artifactBusyId === candidate.id} onOpen={onOpenCandidate} onPublish={onPublishCandidate} onSaveNote={onSaveNote} />)}
          </div> : candidates === null ? <p className="curation-candidate-status__empty">正在同步候选题…</p> : recentCandidate === null ? <p className="curation-candidate-status__empty">候选题生成后会在这里显示。</p> : <div className="curation-candidate-status__recent"><small>最近更新</small><div><span>{ordinalByCandidate.get(recentCandidate.id) ?? "旧"}</span><strong title={recentCandidate.question.title}>{recentCandidate.question.title}</strong><em className={`candidate-status candidate-status--${recentCandidate.status}`}>{candidateStatusLabels[recentCandidate.status]}</em></div></div>}
        </section>
        {activeFilterLabel ? null : <>
        {session.stage === "failed" ? <section className="curation-retry" role="status" aria-live="polite"><TriangleAlert size={17} /><div><strong>本次整理未完成</strong><p>{failureMessage(session.executionErrorCode, session.executionErrorMessage)}</p></div></section> : null}
        {!session.batchStatus && session.stage === "generating" && generationLabel ? <section className="curation-progress" role="status" aria-live="polite" aria-atomic="true"><Activity size={17} /><div><strong>{generationLabel}</strong><p>{session.progress?.completed ?? 0} / {session.progress?.total ?? 0}</p></div></section> : null}
        <details className="curation-runtime-disclosure" open={runtimeOpen}><summary onClick={(event) => { event.preventDefault(); setRuntimeOpen((current) => !current); }}><span><Activity size={16} />运行详情</span><small>{session.usage.callCount} 次调用</small><ChevronDown size={16} /></summary><div className="curation-runtime-disclosure__body"><dl><div><dt>执行状态</dt><dd>{executionStatusLabels[session.executionStatus ?? ""] ?? "尚未启动"}</dd></div>{activeModelLabel ? <div><dt>执行模型</dt><dd title={activeModelLabel}>{activeModelLabel}</dd></div> : null}<div><dt>Token</dt><dd>{tokenLabel(session.usage.totalTokens)}</dd></div></dl><div className="curation-context-compact"><div className="curation-context-ring" style={{ "--context-progress": `${contextPercentage * 3.6}deg` } as CSSProperties}><span>{contextPercentage}%</span></div><div><small>当前上下文 / 压缩阈值</small><strong>{tokenLabel(currentContextTokens)} / {contextThresholdTokens > 0 ? tokenLabel(contextThresholdTokens) : "—"}</strong></div></div></div></details>
        {(session.warnings?.length ?? 0) > 0 ? <details className="curation-runtime-warning" open={warningsOpen}><summary onClick={(event) => { event.preventDefault(); setWarningsOpen((current) => !current); }}><TriangleAlert size={16} />提示 <span>{session.warnings?.length ?? 0}</span></summary><p>{candidateLimitReached ? "已生成前 200 道候选题，请先审核当前结果" : "包含重复或正在整理的资料。题匠会保留全部来源，并在候选生成后合并高置信相似题。"}</p></details> : null}
        </>}
      </>}
    </aside>
  );
}
