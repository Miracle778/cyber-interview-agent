import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Library, MessagesSquare, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { cancelAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { listSources, uploadSource } from "../knowledge/knowledgeApi";
import { listProviders, type WorkspaceConfig } from "../settings/settingsApi";
import { CurationConversation } from "./CurationConversation";
import { CurationArtifactDetail } from "./CurationArtifactDetail";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import { CurationRecycleBin } from "./CurationRecycleBin";
import { CurationSessionList } from "./CurationSessionList";
import { QuestionLibrary } from "./QuestionLibrary";
import { SourceSelectionDialog } from "./SourceSelectionDialog";
import { abandonCurationCommand, createCurationSession, deleteCurationSession, getBulkPublication, getBulkPublicationPreflight, listCurationSessions, listQuestionCandidates, publishQuestionCandidate, retryBulkPublication, retryCurationCommand, retryCurationSession, startBulkPublication, submitCurationCommand, updateQuestionCandidateNote } from "./reviewApi";
import type { BulkPublication, BulkPublicationPreflight, CurationMessage, CurationSession, QuestionCandidate } from "./reviewTypes";

type CatalogView = "sessions" | "library";

function commandId() {
  return globalThis.crypto?.randomUUID?.() ?? `curation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function QuestionCatalog({ workspace }: { workspace: WorkspaceConfig }) {
  const client = useQueryClient();
  const [view, setView] = useState<CatalogView>("sessions");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  const [candidateStatusFilter, setCandidateStatusFilter] = useState<QuestionCandidate["status"] | null>(null);
  const [optimisticMessage, setOptimisticMessage] = useState<CurationMessage | null>(null);
  const [activeInteraction, setActiveInteraction] = useState<{ kind: "command" | "bulk"; executionId: string; commandId?: string; operationId?: string } | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState<"none" | "low" | "medium" | "high">("none");
  const [bulkPreflight, setBulkPreflight] = useState<BulkPublicationPreflight | null>(null);
  const [bulkOperation, setBulkOperation] = useState<BulkPublication | null>(null);
  const focusedWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const sources = useQuery({ queryKey: ["knowledge-sources", workspace.id], queryFn: () => listSources(workspace.id) });
  const sessions = useQuery({
    queryKey: ["review-curation-sessions", workspace.id],
    queryFn: () => listCurationSessions(workspace.id),
    refetchInterval: (query) => query.state.data?.some((item) => !["waiting_for_command", "completed", "failed"].includes(item.stage)) ? 1200 : false,
  });
  const selected = useMemo(() => sessions.data?.find((item) => item.id === selectedId) ?? null, [selectedId, sessions.data]);
  const candidates = useQuery({
    queryKey: ["review-question-candidates", workspace.id],
    queryFn: () => listQuestionCandidates(workspace.id),
    refetchInterval: selected && !["waiting_for_command", "completed", "failed"].includes(selected.stage) ? 1200 : false,
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
  const sourceStates = useMemo(() => {
    const result: Record<string, "not_curated" | "in_progress" | "previously_curated"> = {};
    for (const source of sources.data ?? []) result[source.id] = "not_curated";
    for (const session of sessions.data ?? []) {
      const active = !["waiting_for_command", "completed", "failed"].includes(session.stage);
      for (const sourceId of session.sourceRefs) {
        if (active || result[sourceId] !== "in_progress") result[sourceId] = active ? "in_progress" : "previously_curated";
      }
    }
    return result;
  }, [sessions.data, sources.data]);
  const refresh = () => client.invalidateQueries({ queryKey: ["review-curation-sessions", workspace.id] });
  const refreshCandidates = () => client.invalidateQueries({ queryKey: ["review-question-candidates", workspace.id] });
  useEffect(() => {
    const unhandled = agentEvents.events.filter((event) => event.id > lastHandledEventId.current);
    if (unhandled.length === 0) return;
    lastHandledEventId.current = Math.max(...unhandled.map((event) => event.id));
    const eventTypes = new Set(unhandled.map((event) => event.type));
    if (["curation.stage.changed", "curation.progress.changed", "curation.summary.ready", "session.message.created", "curation.command.resolved", "publication.changed", "execution.completed", "execution.cancelled", "execution.failed", "execution.interrupted"].some((type) => eventTypes.has(type))) {
      void refresh();
    }
    if (["curation.summary.ready", "curation.command.resolved", "publication.changed", "execution.completed"].some((type) => eventTypes.has(type))) {
      void refreshCandidates();
    }
    const terminal = [...unhandled].reverse().find((event) => ["execution.completed", "execution.cancelled", "execution.failed", "execution.interrupted"].includes(event.type) && event.executionId === activeInteraction?.executionId);
    if (activeInteraction?.kind === "bulk" && activeInteraction.operationId && terminal) {
      void getBulkPublication(activeInteraction.operationId).then(setBulkOperation);
    }
  }, [agentEvents.events, activeInteraction]);
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
  const preflightBulk = useMutation({ mutationFn: (sessionId: string) => getBulkPublicationPreflight(sessionId), onSuccess: setBulkPreflight });
  const startBulk = useMutation({ mutationFn: ({ sessionId, version, candidateIds }: { sessionId: string; version: number; candidateIds: string[] }) => startBulkPublication(sessionId, version, candidateIds, commandId()), onSuccess: (accepted) => { setBulkPreflight(null); setBulkOperation(null); setActiveInteraction({ kind: "bulk", executionId: accepted.executionId, operationId: accepted.operationId }); } });
  const retryBulk = useMutation({ mutationFn: (operationId: string) => retryBulkPublication(operationId, commandId()), onSuccess: (accepted) => { setBulkOperation(null); setActiveInteraction({ kind: "bulk", executionId: accepted.executionId, operationId: accepted.operationId }); } });
  const retry = useMutation({
    mutationFn: (sessionId: string) => retryCurationSession(sessionId),
    onSuccess: async (session) => { setSelectedId(session.id); await refresh(); },
  });
  const removeSession = useMutation({
    mutationFn: ({ id, hard }: { id: string; hard: boolean }) => deleteCurationSession(id, hard),
    onSuccess: async (_data, variables) => { if (selectedId === variables.id) setSelectedId(null); await refresh(); },
  });
  const publishCandidate = useMutation({
    mutationFn: (candidateId: string) => publishQuestionCandidate(candidateId, commandId()),
    onSuccess: async () => { await Promise.all([refresh(), refreshCandidates()]); },
  });
  const saveNote = useMutation({
    mutationFn: ({ candidateId, note }: { candidateId: string; note: string }) => updateQuestionCandidateNote(candidateId, note),
    onSuccess: async () => { await refreshCandidates(); },
  });
  const candidateMap = useMemo(() => Object.fromEntries((candidates.data ?? []).map((item) => [item.id, item])), [candidates.data]);
  const selectedCandidates = useMemo(() => (candidates.data ?? []).filter((candidate) => candidate.curationSessionId === selectedId), [candidates.data, selectedId]);
  const focusedCandidate = focusedCandidateId ? candidateMap[focusedCandidateId] ?? null : null;
  const persistedExecutionStatus = activeInteraction && selected?.latestCommand?.executionId === activeInteraction.executionId ? selected?.latestCommand?.lifecycleStatus : null;
  const rawExecutionStatus: string | null = activeInteraction ? agentEvents.executionStateById[activeInteraction.executionId] ?? persistedExecutionStatus ?? "running" : null;
  const executionStatus = rawExecutionStatus === "accepted" ? "running" : rawExecutionStatus;
  const interactionBusy = executionStatus === "running" || executionStatus === "cancelling";
  const formalReplyExists = Boolean(activeInteraction && selected?.messages.some((message) => message.executionId === activeInteraction.executionId && message.role === "assistant" && message.messageKind === "command_receipt"));
  const streamingState = activeInteraction?.kind === "command" && !formalReplyExists ? agentEvents.streamingByExecution[activeInteraction.executionId] ?? (executionStatus ? { text: "", status: executionStatus as "running" | "cancelling" | "cancelled" | "completed" | "failed" | "interrupted" } : null) : null;
  const visibleOptimisticMessage = optimisticMessage && !selected?.messages.some((message) => message.role === "user" && message.payload.resourceId === optimisticMessage.id) ? optimisticMessage : null;

  function handleDeleteSession(id: string, hard: boolean) {
    const message = hard
      ? "永久删除会话及运行历史？此操作不可恢复。"
      : "将会话移到回收站？题目及来源证据会保留。";
    if (globalThis.confirm(message)) removeSession.mutate({ id, hard });
  }

  function sendCommand(text: string) {
    if (!selected) return;
    const idempotencyKey = commandId();
    setOptimisticMessage({ id: idempotencyKey, executionId: selected.executionId, role: "user", content: text, messageKind: "text", payload: {}, createdAt: new Date().toISOString() });
    command.mutate({ session: selected, text, idempotencyKey, modelId: selectedModelId, effort: reasoningEffort });
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    await uploadSource(workspace.id, file);
    await client.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] });
  }

  return (
    <section className={`catalog-workbench${view === "library" ? " catalog-workbench--library" : ""}`} aria-label="题库整理工作台">
      <header className="catalog-toolbar"><div>{selected ? <button type="button" className="catalog-back" onClick={() => { setSelectedId(null); setCandidateStatusFilter(null); }}><ArrowLeft size={16} />返回会话历史</button> : null}<h2>{selected ? selected.title : "题库整理"}</h2><p>{selected ? "在同一会话中查看整理过程、候选总结并完成确认。" : "每组资料对应一个可恢复的 Agent 会话；先查看总结，再用自然语言确认、拒绝或重写。"}</p></div><div className="btn-row"><Button variant="ghost" onClick={() => setTrashOpen(true)}><Trash2 size={16} />回收站</Button><label className="btn btn--secondary btn--md catalog-upload"><span className="btn__label"><Upload size={16} />导入文档</span><input type="file" aria-label="导入文档" onChange={(event) => void handleUpload(event.target.files?.[0])} /></label><Button onClick={() => setDialogOpen(true)}><Sparkles size={16} />AI 整理</Button></div></header>
      <nav className="catalog-secondary-tabs" role="tablist" aria-label="题库整理视图">
        <button type="button" role="tab" aria-selected={view === "sessions"} onClick={() => setView("sessions")}><MessagesSquare size={16} />整理会话</button>
        <button type="button" role="tab" aria-selected={view === "library"} onClick={() => setView("library")}><Library size={16} />题目库</button>
      </nav>
      {view === "sessions" ? selected ? <section className="curation-session-workspace" aria-label="整理会话工作台"><div className="curation-source-stepper" aria-label="本次整理资料">{selected.sources.map((source, index) => <div key={source.id}><span>{index + 1}</span><p><small>资料 {index + 1}</small><strong title={source.filename}>{source.filename}</strong></p></div>)}</div><div ref={focusedWorkspaceRef} className="curation-focus-workspace"><CurationConversation session={selected} candidates={candidateMap} optimisticMessage={visibleOptimisticMessage} busy={interactionBusy || command.isPending} activeExecutionId={activeInteraction?.executionId} streamingState={streamingState} models={modelOptions} selectedModelId={selectedModelId} reasoningEffort={reasoningEffort} onModelChange={setSelectedModelId} onReasoningEffortChange={setReasoningEffort} onStop={() => activeInteraction && stop.mutate(activeInteraction.executionId)} onRetryCommand={() => activeInteraction?.commandId && retryCommand.mutate(activeInteraction.commandId)} onAbandonCommand={() => activeInteraction?.commandId && abandonCommand.mutate(activeInteraction.commandId)} onBulkPublish={() => bulkOperation?.status === "partial_failure" && activeInteraction?.operationId ? retryBulk.mutate(activeInteraction.operationId) : preflightBulk.mutate(selected.id)} bulkBusy={preflightBulk.isPending || startBulk.isPending || retryBulk.isPending || (activeInteraction?.kind === "bulk" && interactionBusy)} bulkRetryAvailable={bulkOperation?.status === "partial_failure"} artifactBusyId={publishCandidate.isPending ? publishCandidate.variables ?? null : saveNote.isPending ? saveNote.variables?.candidateId ?? null : null} onSubmit={sendCommand} onOpenCandidate={setFocusedCandidateId} onPublishCandidate={(candidateId) => publishCandidate.mutate(candidateId)} onSaveNote={(candidateId, note) => saveNote.mutate({ candidateId, note })} />{focusedCandidate ? <CurationArtifactDetail candidate={focusedCandidate} onClose={() => setFocusedCandidateId(null)} /> : <CurationRuntimePanel session={selected} candidates={candidates.isLoading ? null : selectedCandidates} activeModelLabel={modelOptions.find((model) => model.id === selectedModelId)?.label ?? selectedModelId} retrying={retry.isPending} artifactBusyId={publishCandidate.isPending ? publishCandidate.variables ?? null : saveNote.isPending ? saveNote.variables?.candidateId ?? null : null} statusFilter={candidateStatusFilter} onStatusFilterChange={setCandidateStatusFilter} onOpenCandidate={setFocusedCandidateId} onPublishCandidate={(candidateId) => publishCandidate.mutate(candidateId)} onSaveNote={(candidateId, note) => saveNote.mutate({ candidateId, note })} onRetry={() => retry.mutate(selected.id)} />}</div></section> : <CurationSessionList sessions={sessions.data ?? []} onSelect={(id) => { setSelectedId(id); setFocusedCandidateId(null); setCandidateStatusFilter(null); setActiveInteraction(null); setBulkOperation(null); }} onCreate={() => setDialogOpen(true)} onDelete={handleDeleteSession} /> : <QuestionLibrary workspace={workspace} sources={sources.data ?? []} initialCandidateId={focusedCandidateId} onBackToSessions={() => setView("sessions")} onOpenSession={(sessionId) => { setSelectedId(sessionId); setFocusedCandidateId(null); setCandidateStatusFilter(null); setView("sessions"); void refresh(); }} />}
      <SourceSelectionDialog open={dialogOpen} sources={sources.data ?? []} sourceStates={sourceStates} busy={create.isPending} onClose={() => setDialogOpen(false)} onConfirm={(ids) => create.mutate(ids)} />
      <CurationRecycleBin open={trashOpen} workspaceId={workspace.id} onClose={() => setTrashOpen(false)} />
      {bulkPreflight ? <div className="dialog-backdrop" role="presentation"><section className="bulk-publication-dialog" role="dialog" aria-modal="true" aria-labelledby="bulk-publication-title"><h3 id="bulk-publication-title">确认一键发布</h3><p>将发布 {bulkPreflight.publishable.length} 道推荐题；{bulkPreflight.needsReview.length + bulkPreflight.blocked.length} 道需复核题会被跳过。已发布题目不会重复处理。</p><dl><div><dt>可发布</dt><dd>{bulkPreflight.publishable.length}</dd></div><div><dt>需复核</dt><dd>{bulkPreflight.needsReview.length}</dd></div><div><dt>已发布</dt><dd>{bulkPreflight.alreadyPublished.length}</dd></div></dl><footer><Button variant="ghost" onClick={() => setBulkPreflight(null)}>取消</Button><Button disabled={bulkPreflight.publishable.length === 0} loading={startBulk.isPending} onClick={() => startBulk.mutate({ sessionId: bulkPreflight.sessionId, version: bulkPreflight.summaryVersion, candidateIds: bulkPreflight.publishable })}>确认发布</Button></footer></section></div> : null}
    </section>
  );
}
