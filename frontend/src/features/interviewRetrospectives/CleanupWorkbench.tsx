import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowLeftRight, ArrowRight, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, FileText, ListFilter, LocateFixed, Pause, Play, WandSparkles } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { CleanupSegment, CleanupVersion, CorrectionDecisionEdit, SegmentEdit, SpeakerRole, TranscriptCorrection, TranscriptReviewIssue, TranscriptReviewIssueDecisionEdit } from "./retrospectiveTypes";

const ROLE_LABELS: Record<SpeakerRole, string> = {
  interviewer: "面试官",
  candidate: "我",
  unknown: "待确认",
};

const REVIEW_ISSUE_LABELS: Record<TranscriptReviewIssue["issueKind"], string> = {
  uncertain_term: "术语待确认",
  speaker: "说话人待确认",
  semantic: "语义待确认",
};

const ERROR_MESSAGES: Record<string, string> = {
  provider_timeout: "模型响应超时，已经完成的窗口仍然保留。可以重试未完成部分。",
  rate_limited: "模型服务当前繁忙，已经完成的窗口仍然保留。稍后可重试未完成部分。",
  network_error: "连接模型服务时出现网络问题，已经完成的窗口仍然保留。",
  provider_error: "模型服务未能完成本次整理，已经完成的窗口仍然保留。",
  provider_server_error: "模型服务暂时不可用，已经完成的窗口仍然保留。",
  protocol_error: "模型服务返回了无法读取的结果，请重试未完成部分。",
  output_truncated: "模型返回内容不完整，请重试未完成部分。",
  schema_validation_error: "模型返回格式无法用于整理，请重试未完成部分。",
  structured_output_missing: "模型没有返回可用的结构化整理结果。",
  retrospective_cleanup_failed: "本次整理未完成，请重试未完成部分。技术详情可在 Agent 运行中心查看。",
};

function toEdit(segment: CleanupSegment): SegmentEdit {
  const { speakerRole, rawSpeakerLabel, displayName, body, sourceStart, sourceEnd, confidence, uncertaintyReason, ignored } = segment;
  return { speakerRole, rawSpeakerLabel, displayName, body, sourceStart, sourceEnd, confidence, uncertaintyReason, ignored };
}

function parseServerTime(value: string | null | undefined) {
  if (!value) return null;
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function formatElapsed(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1_000));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`;
}

function firstReviewSegment(cleanup: CleanupVersion) {
  const pending = (cleanup.corrections ?? []).find((item) => item.riskLevel === "high" && item.decision === "pending");
  return pending?.segmentId ?? cleanup.segments.find((item) => item.speakerRole === "unknown")?.id ?? cleanup.segments[0]?.id ?? null;
}

interface CleanupWorkbenchProps {
  cleanup: CleanupVersion;
  busy: boolean;
  onSave: (segments: SegmentEdit[], expectedVersion: number, correctionDecisions?: CorrectionDecisionEdit[]) => void;
  onSaveDocument?: (documentBody: string, expectedVersion: number, reviewIssueDecisions: TranscriptReviewIssueDecisionEdit[]) => void;
  onConfirm: (expectedVersion: number) => void;
  onStop: () => void;
  onResume: () => void;
}

function isAmbiguousLocation(issue: TranscriptReviewIssue) {
  return issue.reason.includes("无法在当前目标正文中唯一定位")
    || issue.reason.includes("无法在当前窗口中唯一定位");
}

function replaceIssueText(documentBody: string, issue: TranscriptReviewIssue, replacement: string) {
  if (isAmbiguousLocation(issue)) return null;
  const atExpectedOffset = documentBody.slice(issue.documentStart, issue.documentEnd) === issue.excerpt;
  if (atExpectedOffset) {
    return `${documentBody.slice(0, issue.documentStart)}${replacement}${documentBody.slice(issue.documentEnd)}`;
  }
  const firstMatch = documentBody.indexOf(issue.excerpt);
  if (firstMatch < 0 || documentBody.indexOf(issue.excerpt, firstMatch + 1) >= 0) return null;
  return `${documentBody.slice(0, firstMatch)}${replacement}${documentBody.slice(firstMatch + issue.excerpt.length)}`;
}

function CleanTranscriptWorkbench({ cleanup, busy, onSaveDocument, onConfirm }: CleanupWorkbenchProps) {
  const documentRef = useRef<HTMLTextAreaElement>(null);
  const issueQueueRef = useRef<HTMLDetailsElement>(null);
  const [documentBody, setDocumentBody] = useState(cleanup.documentBody ?? "");
  const [issues, setIssues] = useState(cleanup.reviewIssues ?? []);
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(
    (cleanup.reviewIssues ?? []).find((issue) => issue.decision === "pending")?.id ?? cleanup.reviewIssues?.[0]?.id ?? null,
  );
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDocumentBody(cleanup.documentBody ?? "");
    setIssues(cleanup.reviewIssues ?? []);
    setSelectedIssueId((current) => current && cleanup.reviewIssues?.some((issue) => issue.id === current && issue.decision === "pending")
      ? current
      : cleanup.reviewIssues?.find((issue) => issue.decision === "pending")?.id ?? cleanup.reviewIssues?.[0]?.id ?? null);
    setDirty(false);
  }, [cleanup.id, cleanup.version, cleanup.documentBody, cleanup.reviewIssues]);

  const pendingIssues = issues.filter((issue) => issue.decision === "pending");
  const selectedIssue = issues.find((issue) => issue.id === selectedIssueId) ?? null;
  const reviewedCount = issues.length - pendingIssues.length;
  const selectedPendingIndex = selectedIssue ? pendingIssues.findIndex((issue) => issue.id === selectedIssue.id) : -1;
  const progress = issues.length ? Math.round((reviewedCount / issues.length) * 100) : 100;
  const decisions: TranscriptReviewIssueDecisionEdit[] = issues
    .filter((issue): issue is TranscriptReviewIssue & { decision: "accepted" | "kept" | "manual" } => issue.decision !== "pending")
    .map((issue) => ({ id: issue.id, decision: issue.decision }));

  function decideIssue(issue: TranscriptReviewIssue, decision: "accepted" | "kept" | "manual") {
    if (decision === "accepted" && issue.suggestion) {
      const nextDocument = replaceIssueText(documentBody, issue, issue.suggestion);
      if (nextDocument === null) return;
      setDocumentBody(nextDocument);
    }
    const next = issues.map((item) => item.id === issue.id ? { ...item, decision } : item);
    setIssues(next);
    setDirty(true);
    const currentIndex = next.findIndex((item) => item.id === issue.id);
    const ordered = [...next.slice(currentIndex + 1), ...next.slice(0, currentIndex)];
    setSelectedIssueId(ordered.find((item) => item.decision === "pending")?.id ?? issue.id);
  }

  function selectIssue(issueId: string) {
    setSelectedIssueId(issueId);
    issueQueueRef.current?.removeAttribute("open");
  }

  function locateIssue(issue: TranscriptReviewIssue) {
    const expectedStart = documentBody.slice(issue.documentStart, issue.documentEnd) === issue.excerpt
      ? issue.documentStart
      : documentBody.indexOf(issue.excerpt);
    if (expectedStart < 0) return;
    documentRef.current?.focus();
    documentRef.current?.setSelectionRange(expectedStart, expectedStart + issue.excerpt.length);
  }

  const canSave = cleanup.status === "review_pending" && Boolean(documentBody.trim()) && Boolean(onSaveDocument);
  const canConfirm = cleanup.status === "review_pending" && !dirty && pendingIssues.length === 0 && Boolean(documentBody.trim());
  const selectedIssueIsAmbiguous = selectedIssue ? isAmbiguousLocation(selectedIssue) : false;
  const selectedIssueCanApply = Boolean(
    selectedIssue?.suggestion
    && selectedIssue.suggestion !== selectedIssue.excerpt
    && !selectedIssueIsAmbiguous,
  );

  return <section className="cleanup-workbench clean-transcript" aria-labelledby="cleanup-workbench-title">
    <header className="cleanup-workbench__header">
      <div className="cleanup-workbench__heading">
        <p>准确转写核对</p>
        <h2 id="cleanup-workbench-title">{pendingIssues.length ? `还有 ${pendingIssues.length} 处需要确认` : "整篇文字已可确认"}</h2>
        <span className="cleanup-workbench__description">先确认这份连续文字稿，再基于它提取题目和生成复盘。</span>
      </div>
      <div className="cleanup-workbench__summary" aria-label="文档核对进度">
        <span data-state="automatic"><FileText size={14} /> {documentBody.length.toLocaleString("zh-CN")} 字</span>
        <span data-state={pendingIssues.length ? "pending" : "done"}>已处理 {reviewedCount} / {issues.length}</span>
      </div>
    </header>

    <TaskWorkspace className="clean-transcript__workspace" labelledBy="cleanup-workbench-title">
      <TaskWorkspacePane className="clean-transcript__document" aria-label="准确转写全文">
        <div className="clean-transcript__document-heading"><div><strong>整理后的完整文字</strong><p>可以像编辑普通文档一样直接修改，不需要逐段保存。</p></div><span>唯一采用稿</span></div>
        <textarea
          ref={documentRef}
          aria-label="整理后的完整文字"
          value={documentBody}
          disabled={busy || cleanup.status !== "review_pending"}
          onChange={(event) => { setDocumentBody(event.target.value); setDirty(true); }}
          spellCheck={false}
        />
      </TaskWorkspacePane>

      <TaskWorkspacePane className="clean-transcript__review" aria-label="逐项核对问题">
        <header className="clean-transcript__review-header">
          <div>
            <p>逐项核对</p>
            <strong>{selectedIssue && selectedIssue.decision === "pending" ? `第 ${selectedPendingIndex + 1} / ${pendingIssues.length} 项` : "核对已完成"}</strong>
          </div>
          {pendingIssues.length ? <details className="clean-transcript__queue" ref={issueQueueRef}>
            <summary><ListFilter size={16} />全部问题<span>{pendingIssues.length}</span></summary>
            <div className="clean-transcript__queue-panel">
              <header><strong>待确认问题</strong><small>选择一项开始核对</small></header>
              <div className="clean-transcript__issue-list" aria-label={`待确认问题列表，共 ${pendingIssues.length} 项`}>
                {pendingIssues.map((issue) => <button type="button" key={issue.id} data-selected={selectedIssueId === issue.id} onClick={() => selectIssue(issue.id)}><span>{issue.ordinal}</span><div><strong>{issue.excerpt}</strong><small>{REVIEW_ISSUE_LABELS[issue.issueKind]}</small></div><ChevronRight size={16} /></button>)}
              </div>
            </div>
          </details> : null}
        </header>
        <div className="clean-transcript__progress" aria-label={`已完成 ${progress}%`}><span style={{ width: `${progress}%` }} /></div>

        {selectedIssue && selectedIssue.decision === "pending" ? <article className="clean-transcript__review-card">
          <div className="clean-transcript__review-meta">
            <span>{REVIEW_ISSUE_LABELS[selectedIssue.issueKind]}</span>
            <small>置信度 {Math.round(selectedIssue.confidence * 100)}%</small>
          </div>
          {selectedIssueCanApply ? <section className="clean-transcript__review-change" aria-label="建议修改">
            <span>建议修改</span>
            <div>
              <p><small>原词</small><del>{selectedIssue.excerpt}</del></p>
              <ArrowRight size={18} aria-hidden="true" />
              <p><small>建议词</small><ins>{selectedIssue.suggestion}</ins></p>
            </div>
          </section> : <section className="clean-transcript__review-copy" data-tone="current">
            <span>{selectedIssueIsAmbiguous ? "需要核对的上下文" : "当前文字"}</span>
            <p>{selectedIssue.excerpt}</p>
          </section>}
          {selectedIssueIsAmbiguous && selectedIssue.suggestion ? <section className="clean-transcript__candidate-hint">
            <span>模型标记的候选词</span>
            <strong>{selectedIssue.suggestion}</strong>
            <small>没有找到唯一对应的原词，不能自动替换</small>
          </section> : null}
          <div className="clean-transcript__review-reason"><AlertCircle size={17} /><p>{selectedIssue.reason}</p></div>
          <div className="clean-transcript__issue-actions">
            <Button variant="secondary" onClick={() => decideIssue(selectedIssue, "kept")} disabled={busy}>保留当前文字</Button>
            {selectedIssueCanApply ? <Button onClick={() => decideIssue(selectedIssue, "accepted")} disabled={busy}>采用这处修改</Button> : null}
            <Button variant="ghost" onClick={() => decideIssue(selectedIssue, "manual")} disabled={busy}>我已在全文修改</Button>
          </div>
          <footer className="clean-transcript__review-nav">
            <Button variant="ghost" size="sm" onClick={() => locateIssue(selectedIssue)}><LocateFixed size={16} />在全文定位</Button>
            <div>
              <Button variant="ghost" size="sm" aria-label="上一个待确认问题" onClick={() => setSelectedIssueId(pendingIssues[selectedPendingIndex - 1]?.id ?? selectedIssue.id)} disabled={selectedPendingIndex <= 0}><ChevronLeft size={16} />上一个</Button>
              <Button variant="ghost" size="sm" aria-label="下一个待确认问题" onClick={() => setSelectedIssueId(pendingIssues[selectedPendingIndex + 1]?.id ?? selectedIssue.id)} disabled={selectedPendingIndex < 0 || selectedPendingIndex >= pendingIssues.length - 1}>下一个<ChevronRight size={16} /></Button>
            </div>
          </footer>
        </article> : <div className="clean-transcript__review-complete"><CheckCircle2 size={34} /><strong>所有问题都处理好了</strong><p>保存整理稿后，就可以确认并进入题目提取。</p></div>}
      </TaskWorkspacePane>
    </TaskWorkspace>

    <footer className="cleanup-workbench__footer">
      <div>{dirty ? <><AlertCircle size={18} /><span>有未保存的修改</span></> : pendingIssues.length ? <><AlertCircle size={18} /><span>还需确认 {pendingIssues.length} 处</span></> : <><CheckCircle2 size={18} /><span>这份文字将作为后续题目提取的唯一来源</span></>}</div>
      <div><Button variant="secondary" onClick={() => onSaveDocument?.(documentBody, cleanup.version, decisions)} disabled={busy || !canSave || !dirty}>保存整理稿</Button><Button onClick={() => onConfirm(cleanup.version)} disabled={busy || !canConfirm}>确认并进入题目提取</Button></div>
    </footer>
  </section>;
}

function LegacyCleanupWorkbench({
  cleanup,
  busy,
  onSave,
  onConfirm,
  onStop,
  onResume,
}: CleanupWorkbenchProps) {
  const [segments, setSegments] = useState(cleanup.segments);
  const [corrections, setCorrections] = useState<TranscriptCorrection[]>(cleanup.corrections ?? []);
  const [selectedId, setSelectedId] = useState(firstReviewSegment(cleanup));
  const [manualCorrectionId, setManualCorrectionId] = useState<string | null>(null);
  const [manualCorrectionText, setManualCorrectionText] = useState("");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setSegments(cleanup.segments);
    setCorrections(cleanup.corrections ?? []);
    setSelectedId((current) => current && cleanup.segments.some((item) => item.id === current) ? current : firstReviewSegment(cleanup));
    setManualCorrectionId(null);
    setManualCorrectionText("");
  }, [cleanup.id, cleanup.version, cleanup.segments, cleanup.corrections]);

  useEffect(() => {
    if (!["queued", "running", "stopping"].includes(cleanup.status)) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [cleanup.status, cleanup.activeSince]);

  const uncertainCount = useMemo(
    () => segments.filter((item) => !item.ignored && item.speakerRole === "unknown").length,
    [segments],
  );
  const pendingHighCount = useMemo(
    () => corrections.filter((item) => item.riskLevel === "high" && item.decision === "pending").length,
    [corrections],
  );
  const automaticCorrectionCount = useMemo(
    () => corrections.filter((item) => item.riskLevel === "low" && item.decision === "auto_accepted").length,
    [corrections],
  );
  const highCorrections = useMemo(
    () => corrections.filter((item) => item.riskLevel === "high" && item.decision !== "superseded"),
    [corrections],
  );
  const remainingReviewCount = uncertainCount + pendingHighCount;
  const canConfirm = cleanup.status === "review_pending" && uncertainCount === 0 && pendingHighCount === 0 && segments.some((item) => !item.ignored);
  const selected = segments.find((item) => item.id === selectedId) ?? null;
  const selectedCorrections = corrections.filter((item) => item.segmentId === selectedId && item.decision !== "superseded");
  const selectedAutomaticCorrections = selectedCorrections.filter((item) => item.riskLevel === "low");
  const selectedPendingCorrections = selectedCorrections.filter((item) => item.riskLevel === "high" && item.decision === "pending");
  const selectedResolvedCorrections = selectedCorrections.filter((item) => item.riskLevel === "high" && item.decision !== "pending");
  const activeCorrection = selectedPendingCorrections[0] ?? null;
  const activeCorrectionNumber = activeCorrection ? highCorrections.findIndex((item) => item.id === activeCorrection.id) + 1 : 0;

  function updateSegment(id: string, patch: Partial<CleanupSegment>) {
    setSegments((current) => current.map((item) => {
      if (item.id !== id) return item;
      const next = { ...item, ...patch };
      if (patch.speakerRole && patch.speakerRole !== "unknown") {
        next.displayName = ROLE_LABELS[patch.speakerRole];
        next.uncertaintyReason = null;
      }
      return next;
    }));
  }

  function swapRoles() {
    setSegments((current) => current.map((item) => {
      const speakerRole = item.speakerRole === "candidate" ? "interviewer" : item.speakerRole === "interviewer" ? "candidate" : "unknown";
      return { ...item, speakerRole, displayName: ROLE_LABELS[speakerRole] };
    }));
  }

  function moveToNextIssue(nextCorrections: TranscriptCorrection[], currentId: string) {
    const currentIndex = nextCorrections.findIndex((item) => item.id === currentId);
    const ordered = [...nextCorrections.slice(currentIndex + 1), ...nextCorrections.slice(0, currentIndex + 1)];
    const nextCorrection = ordered.find((item) => item.riskLevel === "high" && item.decision === "pending");
    if (nextCorrection) {
      setSelectedId(nextCorrection.segmentId);
      return;
    }
    const nextUnknown = segments.find((item) => !item.ignored && item.speakerRole === "unknown");
    if (nextUnknown) setSelectedId(nextUnknown.id);
  }

  function decideCorrection(id: string, decision: "accepted" | "kept_original") {
    const nextCorrections = corrections.map((item) => item.id === id ? {
      ...item,
      decision,
      adoptedText: decision === "accepted" ? item.suggestedText : item.originalText,
    } : item);
    setCorrections(nextCorrections);
    moveToNextIssue(nextCorrections, id);
  }

  function beginManualCorrection(correction: TranscriptCorrection) {
    setManualCorrectionId(correction.id);
    setManualCorrectionText(correction.adoptedText ?? correction.suggestedText ?? correction.originalText ?? "");
  }

  function saveManualCorrection() {
    if (!manualCorrectionId || !manualCorrectionText.trim()) return;
    const nextCorrections = corrections.map((item) => item.id === manualCorrectionId
      ? { ...item, decision: "manual" as const, adoptedText: manualCorrectionText }
      : item);
    const completedId = manualCorrectionId;
    setCorrections(nextCorrections);
    setManualCorrectionId(null);
    setManualCorrectionText("");
    moveToNextIssue(nextCorrections, completedId);
  }

  function keepAllPendingOriginals() {
    const nextCorrections = corrections.map((item) => item.decision === "pending" ? {
      ...item,
      decision: "kept_original" as const,
      adoptedText: item.originalText,
    } : item);
    const decisions: CorrectionDecisionEdit[] = nextCorrections
      .filter((item): item is TranscriptCorrection & { decision: "accepted" | "kept_original" | "manual" } => ["accepted", "kept_original", "manual"].includes(item.decision))
      .map((item) => ({ id: item.id, decision: item.decision, manualText: item.decision === "manual" ? item.adoptedText : null }));
    setCorrections(nextCorrections);
    onSave(segments.map(toEdit), cleanup.version, decisions);
  }

  const running = ["queued", "running", "stopping"].includes(cleanup.status);
  const stopped = cleanup.status === "stopped";
  const failed = cleanup.status === "failed";
  const editable = cleanup.status === "review_pending";
  const progressLabel = cleanup.totalItems
    ? `已保存 ${cleanup.completedItems} / ${cleanup.totalItems} 个文本窗口`
    : "正在准备文本窗口";
  const activityLabel = cleanup.activeItems > 1
    ? `正在并行处理 ${cleanup.activeItems} 个文本窗口`
    : cleanup.activeItems === 1
      ? "正在处理当前文本窗口"
      : "正在领取下一个文本窗口";
  const errorMessage = failed
    ? ERROR_MESSAGES[cleanup.lastErrorCode ?? ""] ?? "本次整理未完成，请重试未完成部分。技术详情可在 Agent 运行中心查看。"
    : null;
  const activeAt = parseServerTime(cleanup.activeSince);
  const latestAt = parseServerTime(cleanup.latestProgressAt);
  const elapsedMs = activeAt === null ? 0 : Math.max(0, now - activeAt);
  const quietMs = latestAt === null ? 0 : Math.max(0, now - latestAt);
  const currentWindow = cleanup.currentWorkKey?.match(/^window:(\d+):(\d+)$/);
  const currentWindowLabel = currentWindow
    ? `正在处理原文 ${Number(currentWindow[1]).toLocaleString("en-US")} - ${Number(currentWindow[2]).toLocaleString("en-US")}`
    : activityLabel;
  const correctionDecisions: CorrectionDecisionEdit[] = corrections
    .filter((item): item is TranscriptCorrection & { decision: "accepted" | "kept_original" | "manual" } => ["accepted", "kept_original", "manual"].includes(item.decision))
    .map((item) => ({ id: item.id, decision: item.decision, manualText: item.decision === "manual" ? item.adoptedText : null }));

  return (
    <section className="cleanup-workbench" aria-labelledby="cleanup-workbench-title">
      <header className="cleanup-workbench__header">
        <div className="cleanup-workbench__heading">
          <p>{running ? "Agent 正在整理" : cleanup.status === "confirmed" ? "整理结果已确认" : stopped ? "整理已停止" : failed ? "整理遇到问题" : "整理稿核对"}</p>
          <h2 id="cleanup-workbench-title">{running ? "正在整理复盘文字" : failed ? "整理暂时中断" : remainingReviewCount ? `还需处理 ${remainingReviewCount} 项` : "整理稿已核对完成"}</h2>
          {running || failed ? <span className="cleanup-workbench__description">{progressLabel}</span> : <div className="cleanup-workbench__summary" aria-label="核对进度">
            <span data-state={uncertainCount ? "pending" : "done"}>说话人待确认 {uncertainCount}</span>
            <span data-state={pendingHighCount ? "pending" : "done"}>关键文字待确认 {pendingHighCount}</span>
            {automaticCorrectionCount ? <span data-state="automatic">已自动整理 {automaticCorrectionCount} 处</span> : null}
          </div>}
        </div>
        <div className="cleanup-workbench__actions">
          {editable ? <details className="cleanup-workbench__bulk">
            <summary>批量操作 <ChevronDown size={15} /></summary>
            <div>
              <Button variant="ghost" size="sm" onClick={swapRoles} disabled={busy}><ArrowLeftRight size={16} /> 对调双方身份</Button>
              {pendingHighCount ? <Button variant="ghost" size="sm" onClick={keepAllPendingOriginals} disabled={busy}>全部保留原文并保存（{pendingHighCount}）</Button> : null}
            </div>
          </details> : null}
          {running ? <Button variant="secondary" size="sm" onClick={onStop} disabled={busy}><Pause size={16} /> 停止整理</Button> : null}
          {stopped ? <Button size="sm" onClick={onResume} disabled={busy}><Play size={16} /> 继续整理</Button> : null}
          {failed ? <Button size="sm" onClick={onResume} disabled={busy}><Play size={16} /> 重试未完成部分</Button> : null}
        </div>
      </header>

      {running ? <div className="cleanup-workbench__progress" role="status">
        <div className="cleanup-workbench__progress-copy"><strong>{currentWindowLabel}</strong><p>{progressLabel}{activeAt === null ? "" : ` · 已运行 ${formatElapsed(elapsedMs)}`}，刷新或离开不会丢失已完成结果。</p>{elapsedMs >= 60_000 ? <p>大段录音转写可能需要几分钟，可以离开页面；系统会继续保存每个完成窗口。{quietMs >= 60_000 ? " 当前窗口较久没有新进展，仍可停止后重试。" : ""}</p> : null}</div>
        <div className="cleanup-workbench__meter" role="progressbar" aria-label="文本窗口处理进度" aria-valuemin={0} aria-valuemax={cleanup.totalItems || undefined} aria-valuenow={cleanup.totalItems ? cleanup.completedItems : undefined} data-indeterminate={!cleanup.totalItems}><span style={cleanup.totalItems ? { width: `${Math.min(100, cleanup.completedItems / cleanup.totalItems * 100)}%` } : undefined} /></div>
      </div> : null}
      {errorMessage ? <div className="cleanup-workbench__error" role="alert"><AlertCircle size={18} /><div><strong>整理暂时中断</strong><p>{errorMessage}</p></div></div> : null}

      <TaskWorkspace className="cleanup-workbench__workspace" labelledBy="cleanup-workbench-title">
        <TaskWorkspacePane className="cleanup-segment-list" aria-label="整理后的对话段落">
          {segments.length ? segments.map((segment) => {
            const textIssueCount = corrections.filter((item) => item.segmentId === segment.id && item.riskLevel === "high" && item.decision === "pending").length;
            const needsSpeaker = segment.speakerRole === "unknown" && !segment.ignored;
            const reviewLabel = segment.ignored ? "已忽略" : textIssueCount ? `文字待确认 ${textIssueCount}` : needsSpeaker ? "说话人待确认" : "已确认";
            const needsReview = textIssueCount > 0 || needsSpeaker;
            return <button
                type="button"
                key={segment.id}
                className="cleanup-segment-list__item"
                data-selected={segment.id === selectedId}
                data-review={needsReview}
                data-ignored={segment.ignored}
                onClick={() => setSelectedId(segment.id)}
              >
                <span className="cleanup-segment-list__ordinal">{segment.ordinal}</span>
                <div><div className="cleanup-segment-list__title"><strong>{ROLE_LABELS[segment.speakerRole]}</strong><span data-state={needsReview ? "pending" : "done"}>{reviewLabel}</span></div><p>{segment.body}</p></div>
                {needsReview ? <AlertCircle size={18} aria-label={reviewLabel} /> : <CheckCircle2 size={18} aria-label={reviewLabel} />}
              </button>;
          }) : <div className="cleanup-workbench__empty"><p>{running ? "Agent 正在准备第一批段落。" : "当前没有可核对的段落。"}</p></div>}
        </TaskWorkspacePane>

        <TaskWorkspacePane className="cleanup-segment-detail" aria-label="当前段落详情">
          {selected ? (
            <div>
              <header className="cleanup-segment-detail__header"><div><span>第 {selected.ordinal} 段</span><strong>{ROLE_LABELS[selected.speakerRole]}</strong></div>{selectedPendingCorrections.length ? <span data-state="pending">文字待确认 {selectedPendingCorrections.length}</span> : selected.speakerRole === "unknown" && !selected.ignored ? <span data-state="pending">说话人待确认</span> : <span data-state="done">已确认</span>}</header>
              {selected.uncertaintyReason && selected.speakerRole === "unknown" && !selected.ignored ? <p className="cleanup-segment-detail__notice"><AlertCircle size={16} /> {selected.uncertaintyReason}</p> : null}
              <div className="cleanup-segment-detail__speaker"><label><span>这段是谁说的</span><SelectControl aria-label={`第 ${selected.ordinal} 段说话人`} value={selected.speakerRole} disabled={busy || !editable} onChange={(event) => updateSegment(selected.id, { speakerRole: event.target.value as SpeakerRole })}><option value="interviewer">面试官</option><option value="candidate">我</option><option value="unknown">待确认</option></SelectControl></label></div>
              <div className="cleanup-segment-detail__body"><div className="cleanup-segment-detail__body-heading"><label htmlFor={`cleanup-segment-body-${selected.id}`}><span>模型整理稿</span><small>这里直接展示模型返回的 correctedText；可能改变原意的内容仍需在下方确认。</small></label></div><textarea id={`cleanup-segment-body-${selected.id}`} aria-label="模型整理稿正文" value={selected.body} disabled={busy || !editable} onChange={(event) => updateSegment(selected.id, { body: event.target.value })} /></div>

              {selectedAutomaticCorrections.length ? <details className="cleanup-corrections__automatic">
                <summary><span><WandSparkles size={16} /> 已自动整理 {selectedAutomaticCorrections.length} 处</span><ChevronDown size={16} /></summary>
                <div>{selectedAutomaticCorrections.map((correction) => <p key={correction.id}><strong>{correction.changeType === "formatting" ? "格式" : "识别"}</strong><span>{correction.originalText ?? "原文已清除"} → {correction.adoptedText ?? correction.suggestedText}</span><small>{correction.reason}</small></p>)}</div>
              </details> : null}

              {activeCorrection ? <section className="cleanup-corrections" aria-label="当前文字问题">
                <header><div><p>需要你确认的修改</p><strong>这处变化可能影响原意</strong></div><span>第 {activeCorrectionNumber} / {highCorrections.length} 个文字问题</span></header>
                <article data-risk="high">
                  <p>{activeCorrection.reason}</p>
                  <dl><div><dt>原文</dt><dd>{activeCorrection.originalText ?? "原文已清除"}</dd></div><div><dt>建议</dt><dd>{activeCorrection.suggestedText ?? "没有安全建议，请手动处理"}</dd></div></dl>
                  {manualCorrectionId === activeCorrection.id ? <div className="cleanup-corrections__manual"><label><span>采用文字</span><input aria-label="手工修订文字" value={manualCorrectionText} onChange={(event) => setManualCorrectionText(event.target.value)} disabled={busy || !editable} autoFocus /></label><div><Button variant="secondary" size="sm" onClick={() => setManualCorrectionId(null)} disabled={busy}>取消</Button><Button size="sm" onClick={saveManualCorrection} disabled={busy || !editable || !manualCorrectionText.trim()}>保存手动修改</Button></div></div> : <div className="cleanup-corrections__actions">
                    <Button variant="secondary" size="sm" onClick={() => decideCorrection(activeCorrection.id, "kept_original")} disabled={busy || !editable}>保留原文</Button>
                    {activeCorrection.suggestedText ? <Button size="sm" onClick={() => decideCorrection(activeCorrection.id, "accepted")} disabled={busy || !editable}>采用修改</Button> : null}
                    <Button variant="ghost" size="sm" onClick={() => beginManualCorrection(activeCorrection)} disabled={busy || !editable}>手动修改</Button>
                  </div>}
                </article>
              </section> : selectedResolvedCorrections.length ? <div className="cleanup-corrections__resolved"><CheckCircle2 size={17} /><span>这段的 {selectedResolvedCorrections.length} 处关键文字已经处理</span></div> : null}

              <details className="cleanup-segment-detail__more"><summary>更多段落设置 <ChevronDown size={15} /></summary><div><label><span>显示名称</span><input value={selected.displayName} disabled={busy || !editable} onChange={(event) => updateSegment(selected.id, { displayName: event.target.value })} /></label><label className="cleanup-segment-detail__ignore"><input type="checkbox" checked={selected.ignored} disabled={busy || !editable} onChange={(event) => updateSegment(selected.id, { ignored: event.target.checked })} /><span>忽略这段，不进入后续分析</span></label><p className="cleanup-segment-detail__source">原文位置 {selected.sourceStart.toLocaleString("en-US")} - {selected.sourceEnd.toLocaleString("en-US")}</p></div></details>
            </div>
          ) : <div className="cleanup-workbench__empty"><p>选择一个段落开始核对。</p></div>}
        </TaskWorkspacePane>
      </TaskWorkspace>

      <footer className="cleanup-workbench__footer">
        <div>{failed ? <><AlertCircle size={18} /><span>{progressLabel}{cleanup.failedItems ? `，${cleanup.failedItems} 个窗口待重试` : "，重试后才能确认"}</span></> : remainingReviewCount ? <><AlertCircle size={18} /><span>还需处理 {remainingReviewCount} 项：说话人 {uncertainCount}，关键文字 {pendingHighCount}</span></> : canConfirm ? <><CheckCircle2 size={18} /><span>所有必需项目已处理，可以确认整理结果</span></> : <span>整理完成后可以核对并确认</span>}</div>
        <div><Button variant="secondary" onClick={() => correctionDecisions.length ? onSave(segments.map(toEdit), cleanup.version, correctionDecisions) : onSave(segments.map(toEdit), cleanup.version)} disabled={busy || !editable}>保存并稍后继续</Button><Button onClick={() => onConfirm(cleanup.version)} disabled={busy || !canConfirm}>确认整理结果</Button></div>
      </footer>
    </section>
  );
}

export function CleanupWorkbench(props: CleanupWorkbenchProps) {
  return props.cleanup.documentBody !== null && props.cleanup.documentBody !== undefined
    ? <CleanTranscriptWorkbench {...props} />
    : <LegacyCleanupWorkbench {...props} />;
}
