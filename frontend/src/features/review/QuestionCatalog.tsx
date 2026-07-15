import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Library, MessagesSquare, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { listSources, uploadSource } from "../knowledge/knowledgeApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { CurationConversation } from "./CurationConversation";
import { CurationArtifactDetail } from "./CurationArtifactDetail";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import { CurationRecycleBin } from "./CurationRecycleBin";
import { CurationSessionList } from "./CurationSessionList";
import { QuestionLibrary } from "./QuestionLibrary";
import { SourceSelectionDialog } from "./SourceSelectionDialog";
import { createCurationSession, deleteCurationSession, listCurationSessions, listQuestionCandidates, publishQuestionCandidate, retryCurationSession, submitCurationCommand, updateQuestionCandidateNote } from "./reviewApi";
import type { CurationMessage, CurationSession } from "./reviewTypes";

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
  const [optimisticMessage, setOptimisticMessage] = useState<CurationMessage | null>(null);
  const focusedWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const sources = useQuery({ queryKey: ["knowledge-sources", workspace.id], queryFn: () => listSources(workspace.id) });
  const sessions = useQuery({
    queryKey: ["review-curation-sessions", workspace.id],
    queryFn: () => listCurationSessions(workspace.id),
    refetchInterval: (query) => query.state.data?.some((item) => !["waiting_for_command", "completed", "failed"].includes(item.stage)) ? 1200 : false,
  });
  const candidates = useQuery({ queryKey: ["review-question-candidates", workspace.id], queryFn: () => listQuestionCandidates(workspace.id) });
  const selected = useMemo(() => sessions.data?.find((item) => item.id === selectedId) ?? null, [selectedId, sessions.data]);
  useEffect(() => {
    if (!selected) return;
    focusedWorkspaceRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [selected?.id]);
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
  const create = useMutation({
    mutationFn: (sourceRefs: string[]) => createCurationSession(workspace.id, sourceRefs),
    onSuccess: async (session) => { setSelectedId(session.id); setDialogOpen(false); await refresh(); },
  });
  const command = useMutation({
    mutationFn: ({ session, text, idempotencyKey }: { session: CurationSession; text: string; idempotencyKey: string }) => submitCurationCommand(session, text, idempotencyKey),
    onSettled: async () => { setOptimisticMessage(null); await refresh(); },
  });
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
  const focusedCandidate = focusedCandidateId ? candidateMap[focusedCandidateId] ?? null : null;

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
    command.mutate({ session: selected, text, idempotencyKey });
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    await uploadSource(workspace.id, file);
    await client.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] });
  }

  return (
    <section className="catalog-workbench" aria-label="题库整理工作台">
      <header className="catalog-toolbar"><div>{selected ? <button type="button" className="catalog-back" onClick={() => setSelectedId(null)}><ArrowLeft size={16} />返回会话历史</button> : null}<h2>{selected ? selected.title : "题库整理"}</h2><p>{selected ? "在同一会话中查看整理过程、候选总结并完成确认。" : "每组资料对应一个可恢复的 Agent 会话；先查看总结，再用自然语言确认、拒绝或重写。"}</p></div><div className="btn-row"><Button variant="ghost" onClick={() => setTrashOpen(true)}><Trash2 size={16} />回收站</Button><label className="btn btn--secondary btn--md catalog-upload"><span className="btn__label"><Upload size={16} />导入文档</span><input type="file" aria-label="导入文档" onChange={(event) => void handleUpload(event.target.files?.[0])} /></label><Button onClick={() => setDialogOpen(true)}><Sparkles size={16} />AI 整理</Button></div></header>
      <nav className="catalog-secondary-tabs" role="tablist" aria-label="题库整理视图">
        <button type="button" role="tab" aria-selected={view === "sessions"} onClick={() => setView("sessions")}><MessagesSquare size={16} />整理会话</button>
        <button type="button" role="tab" aria-selected={view === "library"} onClick={() => setView("library")}><Library size={16} />题目库</button>
      </nav>
      {view === "sessions" ? selected ? <section className="curation-session-workspace" aria-label="整理会话工作台"><div className="curation-source-stepper" aria-label="本次整理资料">{selected.sources.map((source, index) => <div key={source.id}><span>{index + 1}</span><p><small>资料 {index + 1}</small><strong title={source.filename}>{source.filename}</strong></p></div>)}</div><div ref={focusedWorkspaceRef} className="curation-focus-workspace"><CurationConversation session={selected} candidates={candidateMap} optimisticMessage={optimisticMessage} busy={command.isPending} artifactBusyId={publishCandidate.isPending ? publishCandidate.variables ?? null : saveNote.isPending ? saveNote.variables?.candidateId ?? null : null} onSubmit={sendCommand} onOpenCandidate={setFocusedCandidateId} onPublishCandidate={(candidateId) => publishCandidate.mutate(candidateId)} onSaveNote={(candidateId, note) => saveNote.mutate({ candidateId, note })} />{focusedCandidate ? <CurationArtifactDetail candidate={focusedCandidate} onClose={() => setFocusedCandidateId(null)} /> : <CurationRuntimePanel session={selected} retrying={retry.isPending} onRetry={() => retry.mutate(selected.id)} />}</div></section> : <CurationSessionList sessions={sessions.data ?? []} onSelect={(id) => { setSelectedId(id); setFocusedCandidateId(null); }} onCreate={() => setDialogOpen(true)} onDelete={handleDeleteSession} /> : <QuestionLibrary workspace={workspace} sources={sources.data ?? []} initialCandidateId={focusedCandidateId} onOpenSession={(sessionId) => { setSelectedId(sessionId); setFocusedCandidateId(null); setView("sessions"); void refresh(); }} />}
      <SourceSelectionDialog open={dialogOpen} sources={sources.data ?? []} sourceStates={sourceStates} busy={create.isPending} onClose={() => setDialogOpen(false)} onConfirm={(ids) => create.mutate(ids)} />
      <CurationRecycleBin open={trashOpen} workspaceId={workspace.id} onClose={() => setTrashOpen(false)} />
    </section>
  );
}
