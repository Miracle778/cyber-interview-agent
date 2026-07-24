import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ClipboardCheck, Pencil, RefreshCw, ShieldCheck, X } from "lucide-react";
import { AgentWorkspaceShell } from "../../shared/agent/AgentWorkspaceShell";
import type { AgentReasoningEffort } from "../../shared/agent/AgentComposer";
import { Button } from "../../shared/ui/Button";
import {
  cancelAgentExecution,
  deleteAgentSession,
  getAgentSession,
  renameAgentSession,
  restoreAgentSession,
  startAgentExecution,
} from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { listProviders } from "../settings/settingsApi";
import { createProfileSession, getUnifiedProfile, listProfileSessions } from "./profileApi";
import { ProfileContextScope } from "./ProfileContextScope";
import { ProfileConversation } from "./ProfileConversation";
import { ProfileSessionList } from "./ProfileSessionList";
import { shouldStreamProfileAnswer } from "./profilePresentation";
import type { ProfileCardCategory } from "./profileTypes";

const terminalExecutionStatuses = new Set(["interrupted", "completed", "failed", "cancelled"]);

function readableTitle(title: string) {
  return ["个人画像对话", "画像会话", "简历助手对话"].includes(title) ? "画像助手对话" : title;
}

function executionLabel(status?: string) {
  if (status === "running") return "正在处理";
  if (status === "cancelling") return "正在停止";
  if (status === "failed") return "需要重试";
  if (status === "interrupted") return "处理已中断";
  if (status === "cancelled") return "已停止";
  return "可继续对话";
}

export function ProfileAgentWorkspace({
  workspaceId,
  focus = {},
  onOpenPending,
}: {
  workspaceId: string;
  focus?: { materialId?: string; materialVersionId?: string; claimId?: string; proposalId?: string };
  onOpenPending?: () => void;
}) {
  const client = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const [scopeCategories, setScopeCategories] = useState<ProfileCardCategory[]>(["experience", "project", "skill"]);
  const [asideOpen, setAsideOpen] = useState(() => globalThis.localStorage?.getItem("profile-agent-aside-open") !== "false");
  const [modelId, setModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState<AgentReasoningEffort>("none");
  const [renaming, setRenaming] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [mutatingId, setMutatingId] = useState<string | null>(null);

  const sessions = useQuery({
    queryKey: ["profile-sessions", workspaceId, "active"],
    queryFn: ({ signal }) => listProfileSessions(workspaceId, signal),
  });
  const archived = useQuery({
    queryKey: ["profile-sessions", workspaceId, "archived"],
    queryFn: ({ signal }) => listProfileSessions(workspaceId, signal, true),
  });
  const profile = useQuery({
    queryKey: ["unified-profile", workspaceId],
    queryFn: ({ signal }) => getUnifiedProfile(workspaceId, signal),
  });
  const providers = useQuery({ queryKey: ["settings-providers"], queryFn: listProviders });
  const models = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled
    ? provider.models.filter((model) => model.enabled).map((model) => ({ id: model.id, label: model.displayName }))
    : []), [providers.data]);
  const detail = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => getAgentSession(sessionId!),
    enabled: Boolean(sessionId),
  });
  const live = useAgentEvents(sessionId);
  const latest = detail.data?.latestExecution ?? null;
  const liveStatus = latest ? live.executionStateById[latest.id] : undefined;
  const executionStatus = latest && terminalExecutionStatuses.has(latest.status) ? latest.status : liveStatus ?? latest?.status;
  const running = ["running", "cancelling"].includes(executionStatus ?? "");
  const streaming = latest ? live.streamingByExecution[latest.id] ?? null : null;
  const latestUserMessage = [...(detail.data?.messages ?? [])].reverse().find(
    (message) => message.role === "user" && message.executionId === latest?.id,
  );
  const streamAnswer = latestUserMessage ? shouldStreamProfileAnswer(latestUserMessage.content) : true;
  const latestEventId = live.events[live.events.length - 1]?.id;

  useEffect(() => {
    if (latestEventId !== undefined) void client.invalidateQueries({ queryKey: ["agent-session", sessionId] });
  }, [client, latestEventId, sessionId]);
  useEffect(() => {
    const configuration = detail.data?.latestExecution?.configuration;
    if (!configuration) return;
    setModelId(configuration.providerModelId ?? "");
    setReasoningEffort(configuration.reasoningEffort);
  }, [detail.data?.latestExecution?.id]);

  async function refreshLists() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["profile-sessions", workspaceId, "active"] }),
      client.invalidateQueries({ queryKey: ["profile-sessions", workspaceId, "archived"] }),
    ]);
  }

  const create = useMutation({
    mutationFn: () => createProfileSession(workspaceId),
    onSuccess: async (value) => {
      await refreshLists();
      setSessionId(value.id);
    },
  });
  const archiveSession = useMutation({
    mutationFn: async (id: string) => {
      setMutatingId(id);
      await deleteAgentSession(id, false);
      return id;
    },
    onSettled: () => setMutatingId(null),
    onSuccess: refreshLists,
  });
  const restoreSession = useMutation({
    mutationFn: async (id: string) => {
      setMutatingId(id);
      return restoreAgentSession(id);
    },
    onSettled: () => setMutatingId(null),
    onSuccess: refreshLists,
  });
  const permanentlyDelete = useMutation({
    mutationFn: async (id: string) => {
      setMutatingId(id);
      await deleteAgentSession(id, true);
      return id;
    },
    onSettled: () => setMutatingId(null),
    onSuccess: refreshLists,
  });
  const rename = useMutation({
    mutationFn: (title: string) => renameAgentSession(sessionId!, workspaceId, title),
    onSuccess: async (value) => {
      setRenaming(false);
      setDraftTitle(value.title);
      client.setQueryData(["agent-session", sessionId], (current: typeof detail.data) => current ? { ...current, title: value.title } : current);
      await refreshLists();
    },
  });
  const send = useMutation({
    mutationFn: (message: string) => startAgentExecution(
      sessionId!,
      { message, focus: { ...focus, categories: scopeCategories } },
      { providerModelId: modelId || null, reasoningEffort },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }),
  });
  const stop = useMutation({
    mutationFn: () => cancelAgentExecution(latest!.id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }),
  });
  const toolEvents = useMemo(
    () => live.events.filter((event) => event.executionId === latest?.id && event.type.startsWith("agent.tool.")),
    [latest?.id, live.events],
  );

  function confirmPermanentDelete(id: string, title: string) {
    if (window.confirm(`永久删除“${title}”及其中的历史消息？\n\n简历和已经确认的信息不会被删除。`)) {
      permanentlyDelete.mutate(id);
    }
  }
  function updateAside(open: boolean) {
    setAsideOpen(open);
    globalThis.localStorage?.setItem("profile-agent-aside-open", String(open));
  }

  if (!sessionId) {
    return <ProfileSessionList
      sessions={sessions.data ?? []}
      archived={archived.data ?? []}
      loading={showRecycleBin ? archived.isLoading : sessions.isLoading}
      creating={create.isPending}
      mutatingId={mutatingId}
      showRecycleBin={showRecycleBin}
      onShowRecycleBin={setShowRecycleBin}
      onCreate={() => create.mutate()}
      onOpen={setSessionId}
      onArchive={(id) => archiveSession.mutate(id)}
      onRestore={(id) => restoreSession.mutate(id)}
      onDeletePermanently={confirmPermanentDelete}
    />;
  }

  const title = readableTitle(detail.data?.title ?? "画像助手对话");
  const busy = Boolean(running || send.isPending || stop.isPending);
  return <AgentWorkspaceShell
    asideOpen={asideOpen}
    onAsideOpenChange={updateAside}
    header={<div className="profile-agent-header">
      <button type="button" aria-label="返回会话记录" onClick={() => setSessionId(null)}><ArrowLeft size={18} /></button>
      <div>
        {renaming ? <form onSubmit={(event) => { event.preventDefault(); const clean = draftTitle.trim(); if (clean) rename.mutate(clean); }}>
          <input autoFocus maxLength={80} aria-label="会话标题" value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
          <button type="submit" aria-label="保存标题" disabled={!draftTitle.trim() || rename.isPending}><Check size={16} /></button>
          <button type="button" aria-label="取消重命名" onClick={() => setRenaming(false)}><X size={16} /></button>
        </form> : <h2><span title={title}>{title}</span><button type="button" aria-label="重命名会话" onClick={() => { setDraftTitle(title); setRenaming(true); }}><Pencil size={14} /></button></h2>}
        <span className={`profile-agent-header__status is-${executionStatus ?? "idle"}`}>{executionLabel(executionStatus)}</span>
      </div>
    </div>}
    conversation={<ProfileConversation
      workspaceId={workspaceId}
      messages={detail.data?.messages ?? []}
      events={toolEvents}
      streaming={streaming}
      executionStatus={executionStatus}
      streamAnswer={streamAnswer}
      busy={busy}
      stopping={stop.isPending}
      models={models}
      modelId={modelId}
      reasoningEffort={reasoningEffort}
      onModelChange={setModelId}
      onReasoningEffortChange={setReasoningEffort}
      onSend={(message) => send.mutate(message)}
      onStop={() => stop.mutate()}
      onChanged={() => client.invalidateQueries({ queryKey: ["agent-session", sessionId] })}
      onOpenPending={onOpenPending}
    />}
    aside={<div className="profile-agent-context">
      <section><h3>本次参考范围</h3><ProfileContextScope profile={profile.data ?? null} selected={scopeCategories} onChange={setScopeCategories} /></section>
      <section className="profile-agent-context__privacy"><ShieldCheck size={18} /><div><h3>使用边界</h3><p>只读取已确认资料；待确认内容和敏感信息不会自动加入画像。</p></div></section>
      <section><h3>待你处理</h3>{(profile.data?.pendingCount ?? 0) > 0
        ? <button type="button" className="profile-agent-context__pending" onClick={onOpenPending} disabled={!onOpenPending}><ClipboardCheck size={18} /><span>{profile.data?.pendingCount} 条画像建议</span></button>
        : <div className="profile-agent-context__empty"><Check size={18} /><span>暂无待确认建议</span></div>}
      </section>
      <section><h3>运行状态</h3><dl><div><dt>连接</dt><dd>{live.status === "connected" ? "正常" : "连接中"}</dd></div><div><dt>本次状态</dt><dd>{executionLabel(executionStatus)}</dd></div><div><dt>模型调用</dt><dd>{detail.data?.usage.callCount ?? 0} 次</dd></div></dl></section>
      <details><summary>技术详情</summary><p>历史消息：{detail.data?.contextCompacted ? "已自动整理" : "完整保留"}</p><p>会话 ID：{sessionId}</p></details>
      {live.executionError ? <div className="profile-agent-context__error" role="alert">{live.executionError.message}</div> : null}
      {detail.isError ? <Button size="sm" variant="secondary" onClick={() => detail.refetch()}><RefreshCw size={14} />重新读取</Button> : null}
    </div>}
  />;
}
