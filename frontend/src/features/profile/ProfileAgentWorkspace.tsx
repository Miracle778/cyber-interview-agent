import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, MessagesSquare, RefreshCw } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { cancelAgentExecution, getAgentSession, startAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { createProfileSession, listProfileSessions } from "./profileApi";
import { ProfileConversation } from "./ProfileConversation";

const terminalExecutionStatuses = new Set(["interrupted", "completed", "failed", "cancelled"]);

export function ProfileAgentWorkspace({ workspaceId, focus = {} }: { workspaceId: string; focus?: { materialId?: string; materialVersionId?: string; claimId?: string; proposalId?: string } }) {
  const client = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const sessions = useQuery({ queryKey: ["profile-sessions", workspaceId], queryFn: ({ signal }) => listProfileSessions(workspaceId, signal) });
  useEffect(() => { if (!sessionId && sessions.data?.[0]) setSessionId(sessions.data[0].id); }, [sessionId, sessions.data]);
  const detail = useQuery({ queryKey: ["agent-session", sessionId], queryFn: () => getAgentSession(sessionId!), enabled: Boolean(sessionId) });
  const live = useAgentEvents(sessionId);
  const latest = detail.data?.latestExecution ?? null;
  const liveStatus = latest ? live.executionStateById[latest.id] : undefined;
  // A restart can recover an orphaned Execution directly in SQLite without a
  // matching SSE terminal event. Durable terminal state must win over stale
  // replayed "running" events.
  const executionStatus = latest && terminalExecutionStatuses.has(latest.status)
    ? latest.status
    : liveStatus ?? latest?.status;
  const busy = ["running", "cancelling"].includes(executionStatus ?? "");
  const streaming = latest ? live.streamingByExecution[latest.id] ?? null : null;
  useEffect(() => { if (live.events.length) void client.invalidateQueries({ queryKey: ["agent-session", sessionId] }); }, [live.events.length, sessionId]);
  const create = useMutation({ mutationFn: () => createProfileSession(workspaceId), onSuccess: async (value) => { await client.invalidateQueries({ queryKey: ["profile-sessions", workspaceId] }); setSessionId(value.id); } });
  const send = useMutation({ mutationFn: (message: string) => startAgentExecution(sessionId!, { message, focus }), onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }) });
  const stop = useMutation({ mutationFn: () => cancelAgentExecution(latest!.id), onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }) });
  const toolEvents = useMemo(
    () => live.events.filter(
      (event) => event.executionId === latest?.id && event.type.startsWith("agent.tool."),
    ),
    [latest?.id, live.events],
  );
  return <section className="profile-agent-workspace">
    <aside className="profile-agent-sessions" aria-label="画像会话">
      <header><div><strong>整理会话</strong><small>{sessions.data?.length ?? 0} 个</small></div><Button size="sm" variant="secondary" loading={create.isPending} onClick={() => create.mutate()} aria-label="新建画像会话"><MessageSquarePlus size={16} /></Button></header>
      <div>{sessions.data?.map((session) => <button key={session.id} className={session.id === sessionId ? "active" : ""} onClick={() => setSessionId(session.id)}><MessagesSquare size={16} /><span>{session.title}</span></button>)}</div>
    </aside>
    {sessionId ? <ProfileConversation workspaceId={workspaceId} messages={detail.data?.messages ?? []} events={toolEvents} streaming={streaming} executionStatus={executionStatus} busy={Boolean(busy || send.isPending || stop.isPending)} stopping={stop.isPending} onSend={(message) => send.mutate(message)} onStop={() => stop.mutate()} onChanged={() => client.invalidateQueries({ queryKey: ["agent-session", sessionId] })} /> : <div className="profile-agent-no-session"><MessagesSquare size={30} /><h2>开始画像会话</h2><p>会话共享已确认画像，但各自保留独立讨论上下文。</p><Button loading={create.isPending} onClick={() => create.mutate()}>新建会话</Button></div>}
    <aside className="profile-agent-runtime"><strong>运行状态</strong><dl><div><dt>当前焦点</dt><dd>{focus.claimId ? "画像建议" : focus.materialVersionId ? "简历版本" : focus.materialId ? "个人材料" : "完整画像"}</dd></div><div><dt>连接</dt><dd>{live.status === "connected" ? "已连接" : "连接中"}</dd></div><div><dt>上下文</dt><dd>{detail.data?.contextCompacted ? "已压缩" : "正常"}</dd></div><div><dt>本会话调用</dt><dd>{detail.data?.usage.callCount ?? 0} 次</dd></div></dl>{live.executionError ? <div role="alert">{live.executionError.message}</div> : null}{detail.isError ? <Button size="sm" variant="secondary" onClick={() => detail.refetch()}><RefreshCw size={14} />重新读取</Button> : null}</aside>
  </section>;
}
