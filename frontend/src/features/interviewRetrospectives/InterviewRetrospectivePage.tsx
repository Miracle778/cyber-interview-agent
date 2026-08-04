import { useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient, type QueryFunctionContext } from "@tanstack/react-query";
import { Archive, ArrowLeft, History, MessageSquareText, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import { ApiError } from "../../shared/api/client";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { createJobTarget, listJobTargets } from "../jobTargets/jobTargetApi";
import { CleanupWorkbench } from "./CleanupWorkbench";
import { RetrospectiveWorkspace } from "./RetrospectiveWorkspace";
import { RetrospectiveCreateFlow, type RetrospectiveCreateValues } from "./RetrospectiveCreateFlow";
import { RetrospectiveList } from "./RetrospectiveList";
import { RetrospectiveLifecycleActions } from "./RetrospectiveLifecycleActions";
import { RetrospectiveHistorySearch } from "./RetrospectiveHistorySearch";
import {
  addSourceVersion,
  batchDecideCandidates,
  confirmCleanup,
  createPublicationDraft,
  createRetrospective,
  decideAction,
  decideCandidate,
  decideQuestion,
  getAnalysisReport,
  getCleanup,
  getCurrentCleanup,
  listActions,
  listCandidates,
  listRetrospectives,
  resumeCleanup,
  resumeAnalysis,
  startAnalysis,
  startCleanup,
  stopAnalysis,
  stopCleanup,
  updateCleanTranscriptDocument,
  updateSegments,
} from "./retrospectiveApi";
import type {
  AnalysisReceipt,
  AnalysisReport,
  AnalysisRun,
  CorrectionDecisionEdit,
  PublicationSection,
  RetrospectiveActionItem,
  RetrospectiveCandidate,
  RetrospectiveCandidateDecision,
  RetrospectiveLifecycle,
  SegmentEdit,
  TranscriptReviewIssueDecisionEdit,
} from "./retrospectiveTypes";
import "./interviewRetrospectives.css";

const TABS: Array<{ value: RetrospectiveLifecycle; label: string; icon: typeof Archive }> = [
  { value: "active", label: "进行中", icon: MessageSquareText },
  { value: "archived", label: "已归档", icon: Archive },
  { value: "recycled", label: "回收站", icon: Trash2 },
];

const EMPTY_STATES: Record<RetrospectiveLifecycle, { title: string; description: string; icon: typeof Archive }> = {
  active: {
    title: "还没有面试复盘",
    description: "新建后，原始文字、整理进度和复盘结果都会保存在当前工作区。",
    icon: MessageSquareText,
  },
  archived: {
    title: "暂无已归档复盘",
    description: "归档后的复盘会集中显示在这里，需要时可以恢复继续查看。",
    icon: Archive,
  },
  recycled: {
    title: "回收站为空",
    description: "移入回收站的复盘会暂时保留在这里，之后可以恢复或永久删除。",
    icon: Trash2,
  },
};

export function InterviewRetrospectivePage({ workspace }: { workspace: WorkspaceConfig | null }) {
  const workspaceId = workspace?.id ?? "";
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestedLifecycle = searchParams.get("lifecycle") as RetrospectiveLifecycle | null;
  const lifecycle = TABS.some((tab) => tab.value === requestedLifecycle) ? requestedLifecycle! : "active";
  const targetId = searchParams.get("jobTargetId") ?? "";
  const selectedId = searchParams.get("retrospectiveId");
  const cleanupId = searchParams.get("cleanupId");
  const requestedQuestionId = searchParams.get("questionId");
  const recordListRequested = searchParams.get("view") === "list";
  const pageMode = searchParams.get("mode") === "history" ? "history" : "records";

  const targetsQuery = useQuery({
    queryKey: ["job-targets", workspaceId],
    queryFn: ({ signal }) => listJobTargets(workspaceId, signal),
    enabled: Boolean(workspaceId),
  });
  const listQueries = useQueries({
    queries: TABS.map((tab) => ({
      queryKey: ["retrospectives", workspaceId, tab.value, targetId],
      queryFn: ({ signal }: QueryFunctionContext) => listRetrospectives(workspaceId, { lifecycle: tab.value, jobTargetId: targetId || undefined }, signal),
      enabled: Boolean(workspaceId && pageMode === "records"),
    })),
  });
  const lifecycleIndex = Math.max(0, TABS.findIndex((tab) => tab.value === lifecycle));
  const listQuery = listQueries[lifecycleIndex];
  const selected = useMemo(() => listQuery.data?.find((item) => item.id === selectedId) ?? listQuery.data?.[0] ?? null, [listQuery.data, selectedId]);
  const currentCleanupQuery = useQuery({
    queryKey: ["cleanup-current", workspaceId, selected?.id],
    queryFn: ({ signal }) => getCurrentCleanup(workspaceId, selected!.id, signal),
    enabled: Boolean(pageMode === "records" && workspaceId && selected && !cleanupId && !selected.activeCleanupVersionId),
  });
  const effectiveCleanupId = cleanupId ?? selected?.activeCleanupVersionId ?? currentCleanupQuery.data?.id ?? null;
  const cleanupQuery = useQuery({
    queryKey: ["cleanup", workspaceId, selected?.id, effectiveCleanupId],
    queryFn: ({ signal }) => getCleanup(workspaceId, selected!.id, effectiveCleanupId!, signal),
    enabled: Boolean(pageMode === "records" && workspaceId && selected && effectiveCleanupId),
    refetchInterval: (query) => ["queued", "running", "stopping"].includes(query.state.data?.status ?? "") ? 1_000 : false,
  });
  const reportQuery = useQuery({
    queryKey: ["retrospective-report", workspaceId, selected?.id],
    queryFn: ({ signal }) => getAnalysisReport(workspaceId, selected!.id, signal),
    enabled: Boolean(pageMode === "records" && workspaceId && selected?.activeAnalysisRunId),
    refetchInterval: (query) => ["queued", "running", "stopping"].includes(query.state.data?.analysisRun.status ?? "") ? 1_000 : false,
  });
  const candidatesQuery = useQuery({
    queryKey: ["retrospective-candidates", workspaceId, selected?.id],
    queryFn: ({ signal }) => listCandidates(workspaceId, selected!.id, signal),
    enabled: Boolean(pageMode === "records" && workspaceId && selected?.activeAnalysisRunId),
    refetchInterval: () => ["queued", "running", "stopping"].includes(reportQuery.data?.analysisRun.status ?? "") ? 1_000 : false,
  });
  const actionsQuery = useQuery({
    queryKey: ["retrospective-actions", workspaceId, selected?.id],
    queryFn: ({ signal }) => listActions(workspaceId, selected!.id, signal),
    enabled: Boolean(pageMode === "records" && workspaceId && selected?.activeAnalysisRunId),
    refetchInterval: () => ["queued", "running", "stopping"].includes(reportQuery.data?.analysisRun.status ?? "") ? 1_000 : false,
  });
  const selectedQuestionId = useMemo(
    () => chooseQuestionId(reportQuery.data ?? null, requestedQuestionId),
    [reportQuery.data, requestedQuestionId],
  );

  function patchSearch(patch: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setSearchParams(next);
  }

  const createFlow = useMutation({
    mutationFn: async (values: RetrospectiveCreateValues) => {
      const retrospective = await createRetrospective(workspaceId, {
        jobTargetId: values.targetId,
        title: values.title,
        roundLabel: values.roundLabel,
        interviewDate: values.interviewDate,
        outcome: "unrecorded",
        note: "",
      });
      const source = await addSourceVersion(workspaceId, retrospective.id, {
        sourceKind: values.sourceKind,
        recordingCoverage: values.recordingCoverage,
        body: values.body,
        fileName: values.fileName,
      });
      try {
        const receipt = await startCleanup(workspaceId, retrospective.id, source.id);
        return { retrospective, receipt, startError: null };
      } catch (reason) {
        return {
          retrospective,
          receipt: null,
          startError: reason instanceof Error ? reason.message : "整理暂时没有启动",
        };
      }
    },
    onSuccess: async ({ retrospective, receipt, startError }) => {
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
      patchSearch({ retrospectiveId: retrospective.id, cleanupId: receipt?.cleanupVersionId ?? null, lifecycle: "active", view: null });
      setCreateOpen(false);
      setError(startError ? `复盘和原文已保存；${startError}，可以稍后继续整理。` : null);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "新建复盘失败"),
  });
  const segmentMutation = useMutation({
    mutationFn: ({ segments, version, correctionDecisions = [] }: { segments: SegmentEdit[]; version: number; correctionDecisions?: CorrectionDecisionEdit[] }) => updateSegments(workspaceId, selected!.id, effectiveCleanupId!, version, segments, correctionDecisions),
    onSuccess: (value) => queryClient.setQueryData(["cleanup", workspaceId, selected?.id, effectiveCleanupId], value),
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("整理结果已在其他位置更新，已为你重新载入最新版本。");
        void cleanupQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "保存修改失败");
    },
  });
  const documentMutation = useMutation({
    mutationFn: ({ body, version, reviewIssueDecisions }: { body: string; version: number; reviewIssueDecisions: TranscriptReviewIssueDecisionEdit[] }) => updateCleanTranscriptDocument(workspaceId, selected!.id, effectiveCleanupId!, version, body, reviewIssueDecisions),
    onSuccess: (value) => queryClient.setQueryData(["cleanup", workspaceId, selected?.id, effectiveCleanupId], value),
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("整理稿已在其他位置更新，已为你重新载入最新版本。");
        void cleanupQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "保存整理稿失败");
    },
  });
  const confirmMutation = useMutation({
    mutationFn: (version: number) => confirmCleanup(workspaceId, selected!.id, effectiveCleanupId!, version),
    onSuccess: async (value) => {
      queryClient.setQueryData(["cleanup", workspaceId, selected?.id, effectiveCleanupId], value);
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
    },
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("整理结果已在其他位置更新，已为你重新载入最新版本。");
        void cleanupQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "确认失败");
    },
  });
  const controlMutation = useMutation({
    mutationFn: async (action: "stop" | "resume") => action === "stop" ? stopCleanup(workspaceId, selected!.id, effectiveCleanupId!) : resumeCleanup(workspaceId, selected!.id, effectiveCleanupId!),
    onSuccess: async (value) => {
      if ("cleanupVersionId" in value) patchSearch({ cleanupId: value.cleanupVersionId });
      await cleanupQuery.refetch();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "整理控制失败"),
  });
  const analysisStartMutation = useMutation({
    mutationFn: (confirmedCleanupId: string) => startAnalysis(workspaceId, selected!.id, confirmedCleanupId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["retrospective-report", workspaceId, selected?.id] });
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "启动分析失败"),
  });
  const analysisControlMutation = useMutation<AnalysisReceipt | AnalysisRun, Error, "stop" | "resume" | "retry">({
    mutationFn: (action: "stop" | "resume" | "retry") => {
      const runId = reportQuery.data!.analysisRun.id;
      if (action === "stop") return stopAnalysis(workspaceId, selected!.id, runId);
      if (action === "resume" || action === "retry") return resumeAnalysis(workspaceId, selected!.id, runId);
      throw new Error("不支持的分析控制动作");
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
      await reportQuery.refetch();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "分析控制失败"),
  });
  const questionDecisionMutation = useMutation({
    mutationFn: (decision: "confirmed" | "rejected") => {
      const question = reportQuery.data!.questions.find((item) => item.id === selectedQuestionId)!;
      return decideQuestion(workspaceId, selected!.id, question.id, decision, question.version);
    },
    onSuccess: async (_question, decision) => {
      await reportQuery.refetch();
      if (decision === "rejected") patchSearch({ questionId: null });
    },
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("题目状态已在其他位置更新，已为你重新载入最新结果。");
        void reportQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "题目确认失败");
    },
  });
  const candidateDecisionMutation = useMutation({
    mutationFn: ({ candidate, decision, targetResourceId }: { candidate: RetrospectiveCandidate; decision: RetrospectiveCandidateDecision; targetResourceId?: string }) => decideCandidate(workspaceId, selected!.id, {
      candidateId: candidate.id,
      action: decision,
      targetResourceId,
      expectedVersion: candidate.version,
    }),
    onSuccess: async () => {
      setError(null);
      await candidatesQuery.refetch();
    },
    onError: (reason) => {
      setError(reason instanceof Error ? reason.message : "候选资料处理失败");
      void candidatesQuery.refetch();
    },
  });
  const candidateBatchMutation = useMutation({
    mutationFn: (candidates: RetrospectiveCandidate[]) => batchDecideCandidates(workspaceId, selected!.id, candidates.map((candidate) => ({
      candidateId: candidate.id,
      action: "reject",
      expectedVersion: candidate.version,
    }))),
    onSuccess: async (results) => {
      const failed = results.filter((result) => result.status === "failed");
      setError(failed.length ? `${failed.length} 项没有处理成功，已保留选择供你重试。` : null);
      await candidatesQuery.refetch();
    },
    onError: (reason) => {
      setError(reason instanceof Error ? reason.message : "批量处理失败，所选候选已保留");
      void candidatesQuery.refetch();
    },
  });
  const actionDecisionMutation = useMutation({
    mutationFn: ({ action, decision }: { action: RetrospectiveActionItem; decision: "completed" | "dismissed" }) => decideAction(workspaceId, selected!.id, action.id, decision, action.version),
    onSuccess: async () => {
      setError(null);
      await actionsQuery.refetch();
    },
    onError: (reason) => {
      setError(reason instanceof Error ? reason.message : "行动项更新失败");
      void actionsQuery.refetch();
    },
  });
  const publicationMutation = useMutation({
    mutationFn: (sections: PublicationSection[]) => createPublicationDraft(workspaceId, selected!.id, sections),
    onSuccess: () => setError(null),
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Knowledge 草稿生成失败"),
  });

  if (!workspace) return <section className="retrospective-page retrospective-page--without-workspace"><header className="retrospective-page__header"><div className="retrospective-page__heading"><p>复盘工作台</p><h1>面试复盘</h1><span className="retrospective-page__description">把录音转写或事后回忆整理成可核对、可继续的复盘记录。</span></div></header><div className="retrospective-page__missing"><MessageSquareText size={32} /><h2>先选择工作区</h2><p>面试文字、整理结果和复盘记录会保存在所选工作区。</p></div></section>;
  const counts = Object.fromEntries(TABS.map((tab, index) => [
    tab.value,
    listQueries[index].isLoading ? null : listQueries[index].data?.length ?? 0,
  ])) as Record<RetrospectiveLifecycle, number | null>;
  const emptyState = !listQuery.isLoading && !listQuery.isError && (listQuery.data?.length ?? 0) === 0;
  const emptyCopy = EMPTY_STATES[lifecycle];
  const EmptyIcon = emptyCopy.icon;
  const focusReview = Boolean(
    !recordListRequested
    && cleanupQuery.data?.status === "review_pending"
    && cleanupQuery.data.documentBody !== null
    && cleanupQuery.data.documentBody !== undefined,
  );
  const focusWorkspace = Boolean(
    pageMode === "records"
    &&
    !recordListRequested
    && selected
    && (selectedId || cleanupId || requestedQuestionId || focusReview),
  );

  function handleSelectedChanged(kind: "lifecycle" | "source" | "deleted") {
    void queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
    void queryClient.invalidateQueries({ queryKey: ["job-targets", workspaceId, selected?.jobTargetId, "retrospective-summary"] });
    if (kind === "source") {
      void reportQuery.refetch();
      if (effectiveCleanupId) void cleanupQuery.refetch();
    } else {
      patchSearch({ retrospectiveId: null, cleanupId: null, questionId: null, view: "list" });
    }
  }

  return (
    <section className={`retrospective-page${focusWorkspace ? " retrospective-page--focused" : pageMode === "history" ? " retrospective-page--history" : " retrospective-page--records"}`}>
      <header className="retrospective-page__header">
        {focusWorkspace && selected ? <>
          <div className="retrospective-page__focus-context">
            <button type="button" className="retrospective-page__focus-back" onClick={() => patchSearch({ retrospectiveId: null, cleanupId: null, questionId: null, view: "list" })}><ArrowLeft size={18} />复盘列表</button>
            <div className="retrospective-page__heading"><p>面试复盘</p><h1 id="retrospective-page-title">{selected.title}</h1><span className="retrospective-page__description">{[selected.roundLabel, selected.interviewDate?.replaceAll("-", "/")].filter(Boolean).join(" · ")}</span></div>
          </div>
          <RetrospectiveLifecycleActions retrospective={selected} onError={setError} onChanged={handleSelectedChanged} />
        </> : <>
          <div className="retrospective-page__heading"><p>复盘工作台</p><h1 id="retrospective-page-title">面试复盘</h1><span className="retrospective-page__description">把录音转写或事后回忆整理成可核对、可继续的复盘记录。</span></div>
          {pageMode === "records" ? <Button onClick={() => setCreateOpen(true)}><Plus size={18} /> 新建复盘</Button> : null}
        </>}
      </header>
      {!focusWorkspace ? <nav className="retrospective-page__mode-tabs" aria-label="面试复盘功能">
        <button type="button" aria-current={pageMode === "records" ? "page" : undefined} onClick={() => patchSearch({ mode: null })}><MessageSquareText size={17} />复盘记录</button>
        <button type="button" aria-current={pageMode === "history" ? "page" : undefined} onClick={() => patchSearch({ mode: "history", retrospectiveId: null, cleanupId: null, questionId: null })}><History size={17} />历史检索</button>
      </nav> : null}
      {!focusWorkspace && pageMode === "records" ? <div className="retrospective-page__controls">
        <div className="retrospective-page__toolbar">
          <div role="tablist" aria-label="复盘生命周期">
            {TABS.map((tab) => <button type="button" role="tab" aria-selected={lifecycle === tab.value} key={tab.value} onClick={() => patchSearch({ lifecycle: tab.value, retrospectiveId: null, cleanupId: null })}><tab.icon size={16} /> {tab.label} <span className="retrospective-page__tab-count">{counts[tab.value] ?? "…"}</span></button>)}
          </div>
          <SelectControl aria-label="求职目标" controlSize="sm" value={targetId} onChange={(event) => patchSearch({ jobTargetId: event.target.value || null, retrospectiveId: null, cleanupId: null })} disabled={targetsQuery.isLoading || !(targetsQuery.data?.length)}>
            <option value="">全部求职目标</option>
            {(targetsQuery.data ?? []).map((target) => <option key={target.id} value={target.id}>{[target.companyName, target.roleName].filter(Boolean).join(" / ") || "岗位信息待补充"}</option>)}
          </SelectControl>
        </div>
        {error ? <div className="retrospective-page__error" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)}>关闭</button></div> : null}
        {listQueries.some((query) => query.isError) || targetsQuery.isError ? <div className="retrospective-page__error" role="alert"><span>复盘记录读取失败，请确认本地服务后重试。</span><button type="button" onClick={() => { listQueries.forEach((query) => { void query.refetch(); }); void targetsQuery.refetch(); }}>重新读取</button></div> : null}
      </div> : error ? <div className="retrospective-page__error" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)}>关闭</button></div> : null}

      {pageMode === "history" ? <RetrospectiveHistorySearch workspaceId={workspaceId} targets={targetsQuery.data ?? []} selectedSearchSetId={searchParams.get("searchSetId")} onSearchSetIdChange={(value) => patchSearch({ searchSetId: value })} /> : emptyState ? <TaskWorkspace className="retrospective-page__workspace retrospective-page__workspace--empty" labelledBy="retrospective-empty-title">
        <TaskWorkspacePane className="retrospective-page__empty-workspace" scroll={false}>
          <span className="retrospective-page__empty-icon"><EmptyIcon size={30} /></span>
          <h2 id="retrospective-empty-title">{targetId ? "当前求职目标下没有复盘" : emptyCopy.title}</h2>
          <p>{targetId ? "可以切换求职目标查看其他记录，或通过右上角新建一场复盘。" : emptyCopy.description}</p>
        </TaskWorkspacePane>
      </TaskWorkspace> : <TaskWorkspace className={`retrospective-page__workspace${focusWorkspace ? " retrospective-page__workspace--focused" : ""}`} labelledBy={focusReview ? "cleanup-workbench-title" : focusWorkspace ? "retrospective-page-title" : "retrospective-page-list-title"}>
        {!focusWorkspace ? <TaskWorkspacePane className="retrospective-page__list-pane" aria-label="面试复盘记录">
          <h2 id="retrospective-page-list-title">复盘记录</h2>
          <RetrospectiveList items={listQuery.data ?? []} targets={targetsQuery.data ?? []} selectedId={selected?.id} loading={listQuery.isLoading} onSelect={(id) => patchSearch({ retrospectiveId: id, cleanupId: null, view: null })} />
        </TaskWorkspacePane> : null}
        <TaskWorkspacePane className="retrospective-page__detail-pane" scroll={false} aria-label="复盘详情">
          {selected && !focusWorkspace ? <RetrospectiveLifecycleActions retrospective={selected} onError={setError} onChanged={handleSelectedChanged} /> : null}
          {selected && reportQuery.data ? <RetrospectiveWorkspace
            retrospective={selected}
            report={reportQuery.data}
            corrections={cleanupQuery.data?.corrections ?? []}
            candidates={candidatesQuery.data ?? []}
            actions={actionsQuery.data ?? []}
            publicationDraft={publicationMutation.data ?? null}
            selectedQuestionId={selectedQuestionId}
            focusMode={focusWorkspace}
            busy={analysisControlMutation.isPending || questionDecisionMutation.isPending}
            candidateBusy={candidateDecisionMutation.isPending || candidateBatchMutation.isPending}
            actionBusy={actionDecisionMutation.isPending}
            publicationBusy={publicationMutation.isPending}
            onSelectQuestion={(id) => patchSearch({ questionId: id })}
            onStop={() => analysisControlMutation.mutate("stop")}
            onResume={() => analysisControlMutation.mutate("resume")}
            onRetry={() => analysisControlMutation.mutate("retry")}
            onDecision={(decision) => questionDecisionMutation.mutate(decision)}
            onCandidateDecision={(candidate, decision, targetResourceId) => candidateDecisionMutation.mutate({ candidate, decision, targetResourceId })}
            onBatchCandidateDecision={(candidates) => candidateBatchMutation.mutate(candidates)}
            onActionDecision={(action, decision) => actionDecisionMutation.mutate({ action, decision })}
            onCreateDraft={(sections) => publicationMutation.mutate(sections)}
            onCorrectionConfirmed={() => { void reportQuery.refetch(); void listQuery.refetch(); void candidatesQuery.refetch(); void actionsQuery.refetch(); }}
          /> : cleanupQuery.data && cleanupQuery.data.status !== "confirmed" ? <CleanupWorkbench cleanup={cleanupQuery.data} busy={segmentMutation.isPending || documentMutation.isPending || confirmMutation.isPending || controlMutation.isPending} onSave={(segments, version, correctionDecisions) => segmentMutation.mutate({ segments, version, correctionDecisions })} onSaveDocument={(body, version, reviewIssueDecisions) => documentMutation.mutate({ body, version, reviewIssueDecisions })} onConfirm={(version) => confirmMutation.mutate(version)} onStop={() => controlMutation.mutate("stop")} onResume={() => controlMutation.mutate("resume")} /> : selected?.activeAnalysisRunId && reportQuery.isPending ? <div className="retrospective-page__empty-detail"><RotateCcw size={28} /><h2>正在读取分析结果</h2><p>已经完成的问题马上会显示在这里。</p></div> : selected ? <RetrospectiveSummary retrospective={selected} actionLabel={selected.activeCleanupVersionId || cleanupQuery.data?.status === "confirmed" ? "开始分析" : "开始整理"} busy={analysisStartMutation.isPending} onStart={selected.activeCleanupVersionId || cleanupQuery.data?.status === "confirmed" ? () => analysisStartMutation.mutate(selected.activeCleanupVersionId ?? cleanupQuery.data!.id) : selected.activeSourceVersionId && selected.activeSourceAvailable ? async () => {
            try {
              const receipt = await startCleanup(workspaceId, selected.id, selected.activeSourceVersionId!);
              patchSearch({ retrospectiveId: selected.id, cleanupId: receipt.cleanupVersionId, questionId: null });
            } catch (reason) { setError(reason instanceof Error ? reason.message : "启动整理失败"); }
          } : undefined} /> : <div className="retrospective-page__empty-detail"><RotateCcw size={28} /><h2>选择一场复盘</h2><p>这里会展示整理进度、说话人校对和下一步。</p></div>}
        </TaskWorkspacePane>
      </TaskWorkspace>}

      {createOpen ? <RetrospectiveCreateFlow targets={targetsQuery.data ?? []} initialTargetId={targetId} busy={createFlow.isPending} onCancel={() => setCreateOpen(false)} onCreateTarget={async (values) => {
        const target = await createJobTarget(workspaceId, values);
        await queryClient.invalidateQueries({ queryKey: ["job-targets", workspaceId] });
        return target;
      }} onSubmit={(values) => createFlow.mutate(values)} /> : null}
    </section>
  );
}

function RetrospectiveSummary({ retrospective, actionLabel = "开始整理", busy = false, onStart }: { retrospective: import("./retrospectiveTypes").InterviewRetrospective; actionLabel?: string; busy?: boolean; onStart?: () => void }) {
  const stage = retrospective.activeCleanupVersionId ? "整理结果已确认" : retrospective.activeSourceVersionId && !retrospective.activeSourceAvailable ? "原文已清除" : retrospective.activeSourceVersionId ? "文字已保存" : "等待文字";
  return <div className="retrospective-summary"><span className="retrospective-summary__icon"><MessageSquareText size={24} /></span><p>{retrospective.roundLabel}</p><h2>{retrospective.title}</h2><dl><div><dt>面试日期</dt><dd>{retrospective.interviewDate?.replaceAll("-", "/") ?? "未记录"}</dd></div><div><dt>当前阶段</dt><dd>{stage}</dd></div></dl>{onStart ? <Button onClick={onStart} loading={busy}>{actionLabel}</Button> : null}</div>;
}

function chooseQuestionId(report: AnalysisReport | null, requestedId: string | null) {
  if (!report) return null;
  const questions = report.questions.filter((item) => !["rejected", "superseded"].includes(item.decisionStatus));
  if (requestedId && questions.some((item) => item.id === requestedId)) return requestedId;
  const failedIds = new Set(report.items.filter((item) => ["retryable", "blocked"].includes(item.status) || item.lastErrorCode).map((item) => item.questionUnitId));
  const failed = questions.find((item) => failedIds.has(item.id));
  if (failed) return failed.id;
  const highRiskIds = new Set(report.analyses.filter((item) => item.verdict === "high_risk").map((item) => item.questionUnitId));
  const highRisk = questions.find((item) => highRiskIds.has(item.id));
  if (highRisk) return highRisk.id;
  const completedIds = new Set(report.analyses.map((item) => item.questionUnitId));
  return questions.find((item) => completedIds.has(item.id))?.id ?? questions[0]?.id ?? null;
}
