import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Library, MessagesSquare, RotateCcw, Sparkles, Trash2, TriangleAlert, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createOperationId } from "../../shared/operationId";
import { Button } from "../../shared/ui/Button";
import { cancelAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { listSources, uploadSource } from "../knowledge/knowledgeApi";
import { listProviders, type WorkspaceConfig } from "../settings/settingsApi";
import { CurationConversation } from "./CurationConversation";
import { CurationArtifactDetail } from "./CurationArtifactDetail";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import type { CurationQualityFilter } from "./CurationRuntimePanel";
import { CurationRecycleBin } from "./CurationRecycleBin";
import { CurationSessionList } from "./CurationSessionList";
import { QuestionLibrary } from "./QuestionLibrary";
import { groupLogicalQuestions } from "./questionGroups";
import { SourceSelectionDialog } from "./SourceSelectionDialog";
import { abandonCurationCommand, createCurationSession, CurationControlError, deleteCurationSession, getBulkPublicationPreflight, getCurationSession, getLatestBulkPublication, getQuestionCandidateOriginSession, listAllQuestionCandidates, listCurationSessions, pauseCurationSession, publishQuestionCandidate, restoreCurationSession, resumeCurationSession, retryBulkPublication, retryCurationCommand, retryCurationSeedTask, startBulkPublication, submitCurationCommand, terminateCurationSession, updateQuestionCandidateNote } from "./reviewApi";
import type { BulkPublicationPreflight, CurationMessage, CurationProvisionalCandidate, CurationSession, QuestionCandidate } from "./reviewTypes";

type CatalogView = "sessions" | "library";
type CurationControlOperation = "pause" | "resume" | "terminate";

interface CurationControlNotice {
  message: string;
  sessionId: string;
  batchVersion: number;
  operation: CurationControlOperation;
}

function commandId() {
  return createOperationId("curation");
}

function curationIsRunning(session: CurationSession) {
  return session.batchStatus === "generating" || session.stage === "pausing";
}

const curationPhaseOrder = { discovery: 1, enrichment: 2 } as const;
const formalTerminalBatchStatuses = new Set(["review_pending", "completed", "terminated"]);

function mergeProvisionalCandidates(current: CurationSession, incoming: CurationSession) {
  const merged = [...(current.provisionalCandidates ?? [])];
  const knownIds = new Set(merged.map((candidate) => candidate.id));
  for (const candidate of incoming.provisionalCandidates ?? []) {
    if (!knownIds.has(candidate.id)) {
      merged.push(candidate);
      knownIds.add(candidate.id);
    }
  }
  return merged;
}

function reconcileCurationSession(current: CurationSession | undefined, incoming: CurationSession) {
  if (!current || current.activeBatchId !== incoming.activeBatchId) return incoming;
  const currentVersion = current.batchVersion ?? 0;
  const incomingVersion = incoming.batchVersion ?? 0;
  if (incomingVersion < currentVersion) return current;
  if (incomingVersion > currentVersion) return incoming;
  if (incoming.batchStatus && formalTerminalBatchStatuses.has(incoming.batchStatus)) return incoming;
  if (current.batchStatus && formalTerminalBatchStatuses.has(current.batchStatus)) return current;
  const currentPhase = current.progress?.phase;
  const incomingPhase = incoming.progress?.phase;
  const currentPhaseOrder = currentPhase ? curationPhaseOrder[currentPhase] : 0;
  const incomingPhaseOrder = incomingPhase ? curationPhaseOrder[incomingPhase] : 0;
  if (incomingPhaseOrder < currentPhaseOrder) return current;
  const samePhase = current.progress?.phase === incoming.progress?.phase;
  return {
    ...incoming,
    progress: {
      ...incoming.progress,
      completed: samePhase ? Math.max(current.progress?.completed ?? 0, incoming.progress?.completed ?? 0) : incoming.progress?.completed ?? 0,
      total: samePhase ? Math.max(current.progress?.total ?? 0, incoming.progress?.total ?? 0) : incoming.progress?.total ?? 0,
      generatedCandidateCount: Math.max(current.progress?.generatedCandidateCount ?? 0, incoming.progress?.generatedCandidateCount ?? 0),
    },
    provisionalCandidates: mergeProvisionalCandidates(current, incoming),
  };
}

export function QuestionCatalog({
  workspace,
  initialSessionId = null,
}: {
  workspace: WorkspaceConfig;
  initialSessionId?: string | null;
}) {
  const client = useQueryClient();
  const [view, setView] = useState<CatalogView>("sessions");
  const [libraryInitialStatus, setLibraryInitialStatus] = useState<QuestionCandidate["status"] | "">("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialSessionId);
  const [directSession, setDirectSession] = useState<CurationSession | null>(null);
  const [originSessionNotice, setOriginSessionNotice] = useState<{ status: "loading" | "recycled" | "projection_missing" | "missing" | "error"; sessionId: string; message: string } | null>(null);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  const [candidateStatusFilter, setCandidateStatusFilter] = useState<QuestionCandidate["status"] | null>(null);
  const [candidateQualityFilter, setCandidateQualityFilter] = useState<CurationQualityFilter | null>(null);
  const [retryingSeedIds, setRetryingSeedIds] = useState<Set<string>>(new Set());
  const [pendingAiPublishId, setPendingAiPublishId] = useState<string | null>(null);
  const [optimisticMessage, setOptimisticMessage] = useState<CurationMessage | null>(null);
  const [activeInteraction, setActiveInteraction] = useState<{ kind: "command" | "bulk"; executionId: string; commandId?: string; operationId?: string } | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState<"none" | "low" | "medium" | "high">("none");
  const [bulkPreflight, setBulkPreflight] = useState<BulkPublicationPreflight | null>(null);
  const [bulkAiConfirmed, setBulkAiConfirmed] = useState(false);
  const [bulkPublishError, setBulkPublishError] = useState<string | null>(null);
  const [controlNotice, setControlNotice] = useState<CurationControlNotice | null>(null);
  const focusedWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const seedRetryKeys = useRef(new Map<string, string>());
  const sources = useQuery({ queryKey: ["knowledge-sources", workspace.id], queryFn: () => listSources(workspace.id) });
  const sessions = useQuery({
    queryKey: ["review-curation-sessions", workspace.id],
    queryFn: async () => {
      const incoming = await listCurationSessions(workspace.id);
      const current = client.getQueryData<CurationSession[]>(["review-curation-sessions", workspace.id]);
      return incoming.map((item) => reconcileCurationSession(current?.find((existing) => existing.id === item.id), item));
    },
    refetchInterval: (query) => query.state.data?.some(curationIsRunning) ? 1200 : false,
  });
  const selected = useMemo(() => sessions.data?.find((item) => item.id === selectedId) ?? (directSession?.id === selectedId ? directSession : null), [directSession, selectedId, sessions.data]);
  const latestBulkPublication = useQuery({
    queryKey: ["review-bulk-publication", selected?.id ?? null],
    queryFn: () => getLatestBulkPublication(selected!.id),
    enabled: Boolean(selected?.id),
    refetchInterval: (query) => ["accepted", "running"].includes(query.state.data?.status ?? "") ? 1000 : false,
  });
  const bulkOperation = latestBulkPublication.data ?? null;
  const bulkPublicationRunning = ["accepted", "running"].includes(bulkOperation?.status ?? "");
  const bulkCatalogRefreshActive = bulkPublicationRunning || (
    activeInteraction?.kind === "bulk"
    && activeInteraction.operationId !== bulkOperation?.id
  );
  useEffect(() => {
    if (!controlNotice || !selected || selected.id !== controlNotice.sessionId) return;
    const versionAdvanced = (selected.batchVersion ?? 0) > controlNotice.batchVersion;
    const operationVisible = controlNotice.operation === "pause"
      ? selected.stage === "pausing" || selected.batchStatus === "paused"
      : controlNotice.operation === "resume"
        ? selected.batchStatus === "generating"
        : selected.batchStatus === "terminated";
    if (versionAdvanced || operationVisible) setControlNotice(null);
  }, [controlNotice, selected]);
  const candidates = useQuery({
    queryKey: ["review-question-candidates", workspace.id],
    queryFn: () => listAllQuestionCandidates(workspace.id),
    refetchInterval: bulkCatalogRefreshActive ? 3000 : selected && curationIsRunning(selected) ? 1200 : false,
  });
  const providers = useQuery({ queryKey: ["settings-providers"], queryFn: listProviders, enabled: Boolean(selectedId) });
  const modelOptions = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled ? provider.models.filter((model) => model.enabled && model.connectivityStatus === "ok").map((model) => ({ id: model.id, label: `${provider.name} / ${model.displayName}` })) : []), [providers.data]);
  const agentEvents = useAgentEvents(typeof EventSource === "undefined" ? null : selectedId);
  const lastHandledEventId = useRef(0);
  useEffect(() => {
    if (!selected) return;
    focusedWorkspaceRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [selected?.id]);
  useEffect(() => {
    if (!selected) return;
    setSelectedModelId(selected.preferredModelId ?? modelOptions[0]?.id ?? "");
    setReasoningEffort(selected.preferredReasoningEffort ?? "none");
    const latest = selected.latestCommand;
    if (latest?.executionId && ["accepted", "running", "interrupted"].includes(latest.lifecycleStatus)) {
      setActiveInteraction((current) => current?.executionId === latest.executionId ? current : { kind: "command", executionId: latest.executionId!, commandId: latest.commandId });
    }
  }, [selected?.id, selected?.preferredModelId, selected?.preferredReasoningEffort, selected?.latestCommand?.executionId, selected?.latestCommand?.lifecycleStatus, modelOptions]);
  useEffect(() => {
    if (!bulkOperation?.executionId || !["accepted", "running"].includes(bulkOperation.status)) return;
    setActiveInteraction((current) => current?.executionId === bulkOperation.executionId ? current : {
      kind: "bulk",
      executionId: bulkOperation.executionId!,
      operationId: bulkOperation.id,
    });
  }, [bulkOperation?.executionId, bulkOperation?.id, bulkOperation?.status]);
  const sourceStates = useMemo(() => {
    const result: Record<string, "not_curated" | "in_progress" | "previously_curated"> = {};
    for (const source of sources.data ?? []) result[source.id] = "not_curated";
    for (const session of sessions.data ?? []) {
      const active = curationIsRunning(session);
      for (const sourceId of session.sourceRefs) {
        if (active || result[sourceId] !== "in_progress") result[sourceId] = active ? "in_progress" : "previously_curated";
      }
    }
    return result;
  }, [sessions.data, sources.data]);
  const refresh = () => client.invalidateQueries({ queryKey: ["review-curation-sessions", workspace.id] });
  const refreshCandidates = () => Promise.all([
    client.invalidateQueries({ queryKey: ["review-question-candidates", workspace.id] }),
    client.invalidateQueries({ queryKey: ["active-review-questions", workspace.id] }),
  ]);
  const finalizedBulkRefresh = useRef<string | null>(null);
  useEffect(() => {
    if (!bulkOperation?.completedAt || finalizedBulkRefresh.current === bulkOperation.id) return;
    finalizedBulkRefresh.current = bulkOperation.id;
    void refreshCandidates();
  }, [bulkOperation?.id, bulkOperation?.completedAt]);
  useEffect(() => {
    const unhandled = agentEvents.events.filter((event) => event.id > lastHandledEventId.current);
    if (unhandled.length === 0) return;
    lastHandledEventId.current = Math.max(...unhandled.map((event) => event.id));
    const eventTypes = new Set(unhandled.map((event) => event.type));
    if (["curation.stage.changed", "curation.progress.changed", "curation.control.changed", "curation.seed.changed", "curation.summary.ready", "session.message.created", "curation.command.resolved", "publication.changed", "execution.completed", "execution.cancelled", "execution.failed", "execution.interrupted"].some((type) => eventTypes.has(type))) {
      void refresh();
    }
    const shouldRefreshForPublication = eventTypes.has("publication.changed") && !bulkCatalogRefreshActive;
    if (shouldRefreshForPublication || ["curation.summary.ready", "curation.command.resolved", "execution.completed"].some((type) => eventTypes.has(type))) {
      void refreshCandidates();
    }
    const terminal = [...unhandled].reverse().find((event) => ["execution.completed", "execution.cancelled", "execution.failed", "execution.interrupted"].includes(event.type) && event.executionId === activeInteraction?.executionId);
    if (activeInteraction?.kind === "bulk" && activeInteraction.operationId && terminal) {
      void client.invalidateQueries({ queryKey: ["review-bulk-publication", selectedId] });
    }
  }, [agentEvents.events, activeInteraction, bulkCatalogRefreshActive, client, selectedId]);
  const create = useMutation({
    mutationFn: (sourceRefs: string[]) => createCurationSession(workspace.id, sourceRefs),
    onSuccess: async (session) => { setSelectedId(session.id); setDialogOpen(false); await refresh(); },
  });
  const command = useMutation({
    mutationFn: ({ session, text, idempotencyKey, modelId, effort }: { session: CurationSession; text: string; idempotencyKey: string; modelId: string; effort: "none" | "low" | "medium" | "high" }) => submitCurationCommand(session, text, idempotencyKey, modelId || null, effort),
    onSuccess: async (accepted) => { setActiveInteraction({ kind: "command", executionId: accepted.executionId, commandId: accepted.commandId }); setOptimisticMessage((current) => current ? { ...current, id: accepted.commandId, executionId: accepted.executionId } : current); await refresh(); },
    onError: () => setOptimisticMessage(null),
  });
  const stop = useMutation({ mutationFn: (executionId: string) => cancelAgentExecution(executionId) });
  const retryCommand = useMutation({ mutationFn: (commandId: string) => retryCurationCommand(commandId), onSuccess: (accepted) => setActiveInteraction({ kind: "command", executionId: accepted.executionId, commandId: accepted.commandId }) });
  const abandonCommand = useMutation({ mutationFn: (commandId: string) => abandonCurationCommand(commandId), onSuccess: async () => { setActiveInteraction(null); setOptimisticMessage(null); await refresh(); } });
  const preflightBulk = useMutation({ mutationFn: (sessionId: string) => getBulkPublicationPreflight(sessionId), onMutate: () => { setBulkPublishError(null); setBulkAiConfirmed(false); }, onSuccess: setBulkPreflight, onError: (error) => setBulkPublishError(error instanceof Error ? error.message : "无法获取发布清单，请稍后重试。") });
  const startBulk = useMutation({ mutationFn: ({ sessionId, version, candidateIds, confirmedAiCandidateIds }: { sessionId: string; version: number; candidateIds: string[]; confirmedAiCandidateIds: string[] }) => startBulkPublication(sessionId, version, candidateIds, commandId(), confirmedAiCandidateIds), onMutate: () => setBulkPublishError(null), onSuccess: (accepted) => { setBulkPreflight(null); setBulkAiConfirmed(false); setBulkPublishError(null); setActiveInteraction({ kind: "bulk", executionId: accepted.executionId, operationId: accepted.operationId }); void client.invalidateQueries({ queryKey: ["review-bulk-publication", selectedId] }); }, onError: (error) => setBulkPublishError(error instanceof Error ? error.message : "批量发布未开始，请刷新清单后重试。") });
  const retryBulk = useMutation({ mutationFn: (operationId: string) => retryBulkPublication(operationId, commandId()), onSuccess: (accepted) => { setActiveInteraction({ kind: "bulk", executionId: accepted.executionId, operationId: accepted.operationId }); void client.invalidateQueries({ queryKey: ["review-bulk-publication", selectedId] }); } });
  const curationControl = useMutation({
    mutationFn: ({ operation, session }: { operation: CurationControlOperation; session: CurationSession }) => {
      if (session.batchVersion === null) throw new Error("当前整理任务缺少可控制的 Batch 版本");
      const request = operation === "pause" ? pauseCurationSession : operation === "resume" ? resumeCurationSession : terminateCurationSession;
      return request(session.id, session.batchVersion, commandId());
    },
    onMutate: () => setControlNotice(null),
    onSuccess: async (session) => {
      setControlNotice(null);
      client.setQueryData<CurationSession[]>(["review-curation-sessions", workspace.id], (current) => current?.map((item) => item.id === session.id ? reconcileCurationSession(item, session) : item));
      setDirectSession((current) => current?.id === session.id ? reconcileCurationSession(current, session) : current);
      setSelectedId(session.id);
      await refresh();
    },
    onError: (error, { operation, session }) => {
      if (error instanceof CurationControlError && error.status === 409) {
        setControlNotice({ message: "整理状态已在其他页面更新，已刷新最新状态。请根据当前状态重试。", sessionId: session.id, batchVersion: session.batchVersion ?? 0, operation });
        void refresh();
        return;
      }
      setControlNotice({ message: "操作未完成，请检查网络连接后重试。当前整理进度已保留。", sessionId: session.id, batchVersion: session.batchVersion ?? 0, operation });
    },
  });
  const removeSession = useMutation({
    mutationFn: ({ id, hard }: { id: string; hard: boolean }) => deleteCurationSession(id, hard),
    onSuccess: async (_data, variables) => { if (selectedId === variables.id) setSelectedId(null); await refresh(); },
  });
  const resolveOriginSession = useMutation({
    mutationFn: getQuestionCandidateOriginSession,
    onSuccess: (origin) => {
      if (origin.status === "available") {
        if (origin.session) {
          setDirectSession(origin.session);
          setSelectedId(origin.sessionId);
          setFocusedCandidateId(null);
          setCandidateStatusFilter(null);
          setOriginSessionNotice(null);
          setView("sessions");
        } else {
          setOriginSessionNotice({ status: "error", sessionId: origin.sessionId, message: "原生成会话返回的数据不完整，暂时无法打开。" });
        }
        return;
      }
      const messages = {
        recycled: "原生成会话在回收站中，恢复后可以继续查看和修改。",
        projection_missing: "生成会话的展示记录不完整，暂时无法打开；题目和来源内容仍然保留。",
        missing: "原生成会话已不存在，无法打开；题目内容仍然保留。",
      } as const;
      setOriginSessionNotice({ status: origin.status, sessionId: origin.sessionId, message: messages[origin.status] });
    },
    onError: () => setOriginSessionNotice({ status: "error", sessionId: "", message: "无法检查原生成会话，请确认后端服务正常后重试。" }),
  });
  const restoreOriginSession = useMutation({
    mutationFn: async (sessionId: string) => {
      await restoreCurationSession(sessionId);
      return getCurationSession(sessionId);
    },
    onSuccess: async (session) => {
      setDirectSession(session);
      setSelectedId(session.id);
      setFocusedCandidateId(null);
      setCandidateStatusFilter(null);
      setOriginSessionNotice(null);
      setView("sessions");
      await refresh();
    },
    onError: (_error, sessionId) => setOriginSessionNotice({ status: "error", sessionId, message: "恢复原生成会话失败，请从回收站检查会话状态后重试。" }),
  });
  const publishCandidate = useMutation({
    mutationFn: ({ candidateId, confirmAiSupplement = false }: { candidateId: string; confirmAiSupplement?: boolean }) => publishQuestionCandidate(candidateId, commandId(), confirmAiSupplement),
    onSuccess: async () => { setPendingAiPublishId(null); await Promise.all([refresh(), refreshCandidates()]); },
  });
  const retrySeed = useMutation({
    mutationFn: ({ item, idempotencyKey }: { item: CurationProvisionalCandidate; idempotencyKey: string }) => retryCurationSeedTask(selected!.id, item.seedTaskId!, item.version ?? 0, idempotencyKey),
    onMutate: ({ item }) => setRetryingSeedIds((current) => new Set(current).add(item.seedTaskId!)),
    onSuccess: async () => { await refresh(); },
    onError: (_error, { item }) => setRetryingSeedIds((current) => { const next = new Set(current); next.delete(item.seedTaskId!); return next; }),
  });
  const saveNote = useMutation({
    mutationFn: ({ candidateId, note }: { candidateId: string; note: string }) => updateQuestionCandidateNote(candidateId, note),
    onSuccess: async () => { await refreshCandidates(); },
  });
  const candidateMap = useMemo(() => Object.fromEntries((candidates.data ?? []).map((item) => [item.id, item])), [candidates.data]);
  const bulkAiCandidateIds = useMemo(() => (bulkPreflight?.publishable ?? []).filter((candidateId) => {
    const basis = candidateMap[candidateId]?.answerBasis ?? "unknown";
    return ["mixed", "model", "unknown"].includes(basis);
  }), [bulkPreflight, candidateMap]);
  const logicalQuestionGroups = useMemo(() => groupLogicalQuestions(candidates.data ?? []), [candidates.data]);
  const publishedCandidateCount = useMemo(() => logicalQuestionGroups.filter((group) => group.status === "published").length, [logicalQuestionGroups]);
  const selectedCandidates = useMemo(() => (candidates.data ?? []).filter((candidate) => candidate.curationSessionId === selectedId), [candidates.data, selectedId]);
  const focusedCandidate = focusedCandidateId ? candidateMap[focusedCandidateId] ?? null : null;
  const persistedExecutionStatus = activeInteraction && selected?.latestCommand?.executionId === activeInteraction.executionId ? selected?.latestCommand?.lifecycleStatus : null;
  const rawExecutionStatus: string | null = activeInteraction ? agentEvents.executionStateById[activeInteraction.executionId] ?? persistedExecutionStatus ?? "running" : null;
  const executionStatus = rawExecutionStatus === "accepted" ? "running" : rawExecutionStatus;
  const interactionBusy = executionStatus === "running" || executionStatus === "cancelling";
  const formalReplyExists = Boolean(activeInteraction && selected?.messages.some((message) => message.executionId === activeInteraction.executionId && message.role === "assistant" && message.messageKind === "command_receipt"));
  const streamingState = activeInteraction?.kind === "command" && !formalReplyExists ? agentEvents.streamingByExecution[activeInteraction.executionId] ?? (executionStatus ? { text: "", status: executionStatus as "running" | "cancelling" | "cancelled" | "completed" | "failed" | "interrupted" } : null) : null;
  const visibleOptimisticMessage = optimisticMessage && !selected?.messages.some((message) => message.role === "user" && message.payload.resourceId === optimisticMessage.id) ? optimisticMessage : null;

  useEffect(() => {
    if (!selected) return;
    const retryableIds = new Set((selected.provisionalCandidates ?? []).filter((item) => ["retryable", "skipped"].includes(item.status ?? "")).map((item) => item.seedTaskId).filter((id): id is string => Boolean(id)));
    setRetryingSeedIds((current) => {
      const next = new Set([...current].filter((id) => retryableIds.has(id)));
      if (next.size === current.size && [...next].every((id) => current.has(id))) return current;
      for (const id of seedRetryKeys.current.keys()) if (!retryableIds.has(id)) seedRetryKeys.current.delete(id);
      return next;
    });
  }, [selected?.provisionalCandidates]);

  function handleDeleteSession(id: string, hard: boolean) {
    const message = hard
      ? "永久删除会话及运行历史？关联题目、来源证据和发布记录会保留，但聊天与 checkpoint 无法恢复。"
      : "归档这个会话？它会从会话列表隐藏，可在回收站恢复；题目及来源证据会保留。";
    if (globalThis.confirm(message)) removeSession.mutate({ id, hard });
  }

  function handleOpenOriginSession(candidateId: string) {
    setOriginSessionNotice({ status: "loading", sessionId: "", message: "正在查找原生成会话…" });
    resolveOriginSession.mutate(candidateId);
  }

  function returnToCurationSessions() {
    setView("sessions");
    setSelectedId(null);
    setDirectSession(null);
    setFocusedCandidateId(null);
    setCandidateStatusFilter(null);
  }

  function sendCommand(text: string) {
    if (!selected) return;
    const idempotencyKey = commandId();
    setOptimisticMessage({ id: idempotencyKey, executionId: selected.executionId, role: "user", content: text, messageKind: "text", payload: {}, createdAt: new Date().toISOString() });
    command.mutate({ session: selected, text, idempotencyKey, modelId: selectedModelId, effort: reasoningEffort });
  }

  function requestCandidatePublication(candidateId: string) {
    const candidate = candidateMap[candidateId];
    if (candidate && ["mixed", "model", "unknown"].includes(candidate.answerBasis ?? "source")) {
      setPendingAiPublishId(candidateId);
      return;
    }
    publishCandidate.mutate({ candidateId });
  }

  function retryOneSeed(item: CurationProvisionalCandidate) {
    if (!item.seedTaskId || retryingSeedIds.has(item.seedTaskId)) return;
    const idempotencyKey = seedRetryKeys.current.get(item.seedTaskId) ?? commandId();
    seedRetryKeys.current.set(item.seedTaskId, idempotencyKey);
    retrySeed.mutate({ item, idempotencyKey });
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    await uploadSource(workspace.id, file);
    await client.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] });
  }

  return (
    <section className={`catalog-workbench${view === "library" ? " catalog-workbench--library" : ""}`} aria-label="题库整理工作台">
      <header className="catalog-toolbar"><div><h2>{selected ? selected.title : view === "library" ? "题目库" : "题库整理"}</h2><p>{selected ? "在同一会话中查看整理过程、候选总结并完成确认。" : view === "library" ? "浏览、筛选并管理候选题和已入库题目。" : "每组资料对应一个可恢复的 Agent 会话；先查看总结，再用自然语言确认、拒绝或重写。"}</p></div><div className="btn-row"><Button variant="ghost" onClick={() => setTrashOpen(true)}><Trash2 size={16} />回收站</Button><label className="btn btn--secondary btn--md catalog-upload"><span className="btn__label"><Upload size={16} />导入文档</span><input type="file" aria-label="导入文档" onChange={(event) => void handleUpload(event.target.files?.[0])} /></label><Button onClick={() => setDialogOpen(true)}><Sparkles size={16} />AI 整理</Button></div></header>
      <nav className="catalog-secondary-tabs" role="tablist" aria-label="题库整理视图">
        <button type="button" role="tab" aria-selected={view === "sessions"} onClick={() => setView("sessions")}><MessagesSquare size={16} />整理会话</button>
        <button type="button" role="tab" aria-selected={view === "library"} onClick={() => { setLibraryInitialStatus(""); setView("library"); }}><Library size={16} />题目库</button>
      </nav>
      {selected || view === "library" ? <nav className="catalog-context-nav" aria-label="当前位置导航"><button type="button" className="catalog-back" onClick={returnToCurationSessions}><ArrowLeft size={17} />返回整理会话</button><span aria-current="page">{selected ? selected.title : "题目库"}</span></nav> : null}
      {originSessionNotice ? <div className={`catalog-origin-notice${originSessionNotice.status === "error" || originSessionNotice.status === "missing" || originSessionNotice.status === "projection_missing" ? " catalog-origin-notice--error" : ""}`} role={originSessionNotice.status === "loading" ? "status" : "alert"}><AlertTriangle size={18} /><div><strong>{originSessionNotice.status === "loading" ? "正在定位会话" : "无法直接打开生成会话"}</strong><span>{originSessionNotice.message}</span></div>{originSessionNotice.status === "recycled" ? <Button size="sm" variant="secondary" loading={restoreOriginSession.isPending} onClick={() => restoreOriginSession.mutate(originSessionNotice.sessionId)}><RotateCcw size={15} />恢复并打开</Button> : null}<button type="button" aria-label="关闭会话提示" onClick={() => setOriginSessionNotice(null)}><X size={17} /></button></div> : null}
      {view === "sessions" ? selected ? <section className="curation-session-workspace" aria-label="整理会话工作台">
        <div className="curation-source-stepper" aria-label="本次整理资料">{selected.sources.map((source, index) => <div key={source.id}><span>{index + 1}</span><p><small>资料 {index + 1}</small><strong title={source.filename}>{source.filename}</strong></p></div>)}</div>
        <div ref={focusedWorkspaceRef} className="curation-focus-workspace">
          <CurationConversation session={selected} candidates={candidateMap} optimisticMessage={visibleOptimisticMessage} busy={interactionBusy || command.isPending} activeExecutionId={activeInteraction?.executionId} streamingState={streamingState} models={modelOptions} selectedModelId={selectedModelId} reasoningEffort={reasoningEffort} onModelChange={setSelectedModelId} onReasoningEffortChange={setReasoningEffort} onStop={() => { const executionId = bulkOperation && ["accepted", "running"].includes(bulkOperation.status) ? bulkOperation.executionId : activeInteraction?.executionId; if (executionId) stop.mutate(executionId); }} onRetryCommand={() => activeInteraction?.commandId && retryCommand.mutate(activeInteraction.commandId)} onAbandonCommand={() => activeInteraction?.commandId && abandonCommand.mutate(activeInteraction.commandId)} onBulkPublish={() => bulkOperation && ["partial_failure", "failed", "cancelled", "interrupted"].includes(bulkOperation.status) ? retryBulk.mutate(bulkOperation.id) : preflightBulk.mutate(selected.id)} bulkOperation={bulkOperation} bulkBusy={preflightBulk.isPending || startBulk.isPending || retryBulk.isPending || Boolean(bulkOperation && ["accepted", "running"].includes(bulkOperation.status)) || (activeInteraction?.kind === "bulk" && interactionBusy)} bulkStopping={stop.isPending && activeInteraction?.kind === "bulk"} bulkRetrying={retryBulk.isPending} bulkDisabledReason={curationIsRunning(selected) ? "整理完成后可一键发布" : null} bulkRetryAvailable={Boolean(bulkOperation && ["partial_failure", "failed", "cancelled", "interrupted"].includes(bulkOperation.status))} artifactBusyId={publishCandidate.isPending ? publishCandidate.variables?.candidateId ?? null : saveNote.isPending ? saveNote.variables?.candidateId ?? null : null} onSubmit={sendCommand} onOpenCandidate={setFocusedCandidateId} onPublishCandidate={requestCandidatePublication} onSaveNote={(candidateId, note) => saveNote.mutate({ candidateId, note })} />
          {focusedCandidate ? <CurationArtifactDetail candidate={focusedCandidate} onClose={() => setFocusedCandidateId(null)} /> : <CurationRuntimePanel session={selected} candidates={candidates.isLoading ? null : selectedCandidates} activeModelLabel={modelOptions.find((model) => model.id === selectedModelId)?.label ?? selectedModelId} controlPending={curationControl.isPending ? curationControl.variables?.operation ?? null : null} controlNotice={controlNotice?.message ?? null} artifactBusyId={publishCandidate.isPending ? publishCandidate.variables?.candidateId ?? null : saveNote.isPending ? saveNote.variables?.candidateId ?? null : null} statusFilter={candidateStatusFilter} qualityFilter={candidateQualityFilter} onStatusFilterChange={(value) => { setCandidateStatusFilter(value); if (value) setCandidateQualityFilter(null); }} onQualityFilterChange={(value) => { setCandidateQualityFilter(value); if (value) setCandidateStatusFilter(null); }} onOpenCandidate={setFocusedCandidateId} onPublishCandidate={requestCandidatePublication} onSaveNote={(candidateId, note) => saveNote.mutate({ candidateId, note })} onPause={() => curationControl.mutate({ operation: "pause", session: selected })} onResume={() => curationControl.mutate({ operation: "resume", session: selected })} onTerminate={() => curationControl.mutate({ operation: "terminate", session: selected })} retryingSeedIds={retryingSeedIds} onRetrySeed={retryOneSeed} />}
        </div>
      </section> : <CurationSessionList sessions={sessions.data ?? []} candidateCount={logicalQuestionGroups.length} publishedCount={publishedCandidateCount} onSelect={(id) => { setDirectSession(null); setSelectedId(id); setFocusedCandidateId(null); setCandidateStatusFilter(null); setCandidateQualityFilter(null); setActiveInteraction(null); setControlNotice(null); }} onCreate={() => setDialogOpen(true)} onDelete={handleDeleteSession} onOpenLibrary={(status) => { setLibraryInitialStatus(status ?? ""); setView("library"); }} /> : <QuestionLibrary workspace={workspace} sources={sources.data ?? []} initialCandidateId={focusedCandidateId} initialStatus={libraryInitialStatus} onBackToSessions={() => setView("sessions")} onOpenSession={handleOpenOriginSession} onOpenDirectSession={(session) => { setDirectSession(session); setSelectedId(session.id); setFocusedCandidateId(null); setView("sessions"); }} />}
      <SourceSelectionDialog open={dialogOpen} sources={sources.data ?? []} sourceStates={sourceStates} busy={create.isPending} onClose={() => setDialogOpen(false)} onConfirm={(ids) => create.mutate(ids)} />
      <CurationRecycleBin open={trashOpen} workspaceId={workspace.id} onClose={() => setTrashOpen(false)} />
      {bulkPreflight ? <div className="dialog-backdrop" role="presentation"><section className="bulk-publication-dialog" role="dialog" aria-modal="true" aria-labelledby="bulk-publication-title"><h3 id="bulk-publication-title">确认一键发布</h3><p>将发布 {bulkPreflight.publishable.length} 道推荐题；{bulkPreflight.needsReview.length + bulkPreflight.blocked.length} 道暂不发布。已发布题目不会重复处理。</p><dl><div><dt>本次发布</dt><dd>{bulkPreflight.publishable.length}</dd></div><div><dt>暂不发布</dt><dd>{bulkPreflight.needsReview.length + bulkPreflight.blocked.length}</dd></div><div><dt>已发布</dt><dd>{bulkPreflight.alreadyPublished.length}</dd></div></dl>{bulkAiCandidateIds.length > 0 ? <label className="bulk-publication-dialog__ai-confirm"><input type="checkbox" checked={bulkAiConfirmed} onChange={(event) => setBulkAiConfirmed(event.target.checked)} /><span><strong>其中 {bulkAiCandidateIds.length} 道含 AI 补充或来源依据待确认</strong><small>我已核对这些题目的答案和来源，确认继续批量发布。</small></span></label> : null}{bulkPublishError ? <p className="bulk-publication-dialog__error" role="alert">{bulkPublishError}</p> : null}<footer><Button variant="ghost" onClick={() => { setBulkPreflight(null); setBulkAiConfirmed(false); setBulkPublishError(null); }}>取消</Button><Button disabled={bulkPreflight.publishable.length === 0 || (bulkAiCandidateIds.length > 0 && !bulkAiConfirmed)} loading={startBulk.isPending} onClick={() => startBulk.mutate({ sessionId: bulkPreflight.sessionId, version: bulkPreflight.summaryVersion, candidateIds: bulkPreflight.publishable, confirmedAiCandidateIds: bulkAiConfirmed ? bulkAiCandidateIds : [] })}>确认发布</Button></footer></section></div> : null}
      {pendingAiPublishId ? <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPendingAiPublishId(null); }}><section className="ai-publication-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-publication-title"><TriangleAlert size={22} /><div><h3 id="ai-publication-title">确认 AI 补全风险</h3><p>这道题的答案含 AI 补全、主要由 AI 生成，或来源依据尚未确认。请先核对题目、答案和来源证据。</p></div><footer><Button variant="ghost" onClick={() => setPendingAiPublishId(null)}>返回核对</Button><Button loading={publishCandidate.isPending} onClick={() => publishCandidate.mutate({ candidateId: pendingAiPublishId, confirmAiSupplement: true })}>我已核对，继续发布</Button></footer></section></div> : null}
    </section>
  );
}
