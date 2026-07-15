import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, MessagesSquare, Sparkles, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { listSources, uploadSource } from "../knowledge/knowledgeApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { CurationConversation } from "./CurationConversation";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import { CurationSessionList } from "./CurationSessionList";
import { QuestionLibrary } from "./QuestionLibrary";
import { SourceSelectionDialog } from "./SourceSelectionDialog";
import { createCurationSession, deleteCurationSession, listCurationSessions, retryCurationSession, submitCurationCommand } from "./reviewApi";
import type { CurationMessage, CurationSession } from "./reviewTypes";

type CatalogView = "sessions" | "library";

function commandId() {
  return globalThis.crypto?.randomUUID?.() ?? `curation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function QuestionCatalog({ workspace }: { workspace: WorkspaceConfig }) {
  const client = useQueryClient();
  const [view, setView] = useState<CatalogView>("sessions");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  const [optimisticMessage, setOptimisticMessage] = useState<CurationMessage | null>(null);
  const sources = useQuery({ queryKey: ["knowledge-sources", workspace.id], queryFn: () => listSources(workspace.id) });
  const sessions = useQuery({
    queryKey: ["review-curation-sessions", workspace.id],
    queryFn: () => listCurationSessions(workspace.id),
    refetchInterval: (query) => query.state.data?.some((item) => !["waiting_for_command", "completed", "failed"].includes(item.stage)) ? 1200 : false,
  });
  useEffect(() => {
    if (!selectedId && sessions.data?.[0]) setSelectedId(sessions.data[0].id);
  }, [selectedId, sessions.data]);
  const selected = useMemo(() => sessions.data?.find((item) => item.id === selectedId) ?? sessions.data?.[0] ?? null, [selectedId, sessions.data]);
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
      <header className="catalog-toolbar"><div><h2>题库整理</h2><p>每组资料对应一个可恢复的 Agent 会话；先查看总结，再用自然语言确认、拒绝或重写。</p></div><div className="btn-row"><label className="btn btn--secondary btn--md catalog-upload"><span className="btn__label"><Upload size={16} />导入文档</span><input type="file" aria-label="导入文档" onChange={(event) => void handleUpload(event.target.files?.[0])} /></label><Button onClick={() => setDialogOpen(true)}><Sparkles size={16} />AI 整理</Button></div></header>
      <nav className="catalog-secondary-tabs" role="tablist" aria-label="题库整理视图">
        <button type="button" role="tab" aria-selected={view === "sessions"} onClick={() => setView("sessions")}><MessagesSquare size={16} />整理会话</button>
        <button type="button" role="tab" aria-selected={view === "library"} onClick={() => setView("library")}><Library size={16} />题目库</button>
      </nav>
      {view === "sessions" ? <div className="curation-workbench"><CurationConversation session={selected} optimisticMessage={optimisticMessage} busy={command.isPending} onSubmit={sendCommand} onOpenCandidate={(candidateId) => { setFocusedCandidateId(candidateId); setView("library"); }} /><CurationSessionList sessions={sessions.data ?? []} selectedId={selected?.id ?? null} onSelect={setSelectedId} onCreate={() => setDialogOpen(true)} onDelete={handleDeleteSession} /><CurationRuntimePanel session={selected} retrying={retry.isPending} onRetry={() => selected && retry.mutate(selected.id)} /></div> : <QuestionLibrary workspace={workspace} sources={sources.data ?? []} initialCandidateId={focusedCandidateId} onOpenSession={(sessionId) => { setSelectedId(sessionId); setView("sessions"); void refresh(); }} />}
      <SourceSelectionDialog open={dialogOpen} sources={sources.data ?? []} sourceStates={sourceStates} busy={create.isPending} onClose={() => setDialogOpen(false)} onConfirm={(ids) => create.mutate(ids)} />
    </section>
  );
}
