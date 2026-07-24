import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, MessagesSquare, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { cancelAgentExecution, deleteAgentSession, getAgentSession, startAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { createProfileSession, listProfileSessions } from "./profileApi";
import { ProfileConversation } from "./ProfileConversation";
import { shouldStreamProfileAnswer } from "./profilePresentation";

const terminalExecutionStatuses = new Set(["interrupted", "completed", "failed", "cancelled"]);

function sessionTitle(title: string) {
  return title === "个人画像对话" || title === "画像会话" ? "简历助手对话" : title;
}

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
  const latestUserMessage = [...(detail.data?.messages ?? [])].reverse().find(
    (message) => message.role === "user" && message.executionId === latest?.id,
  );
  const streamAnswer = latestUserMessage
    ? shouldStreamProfileAnswer(latestUserMessage.content)
    : true;
  const latestEventId = live.events[live.events.length - 1]?.id;
  useEffect(() => {
    if (latestEventId !== undefined) {
      void client.invalidateQueries({ queryKey: ["agent-session", sessionId] });
    }
  }, [client, latestEventId, sessionId]);
  const create = useMutation({ mutationFn: () => createProfileSession(workspaceId), onSuccess: async (value) => { await client.invalidateQueries({ queryKey: ["profile-sessions", workspaceId] }); setSessionId(value.id); } });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAgentSession(id, true),
    onSuccess: (_, deletedId) => {
      const remaining = (sessions.data ?? []).filter((session) => session.id !== deletedId);
      client.setQueryData(["profile-sessions", workspaceId], remaining);
      client.removeQueries({ queryKey: ["agent-session", deletedId] });
      setSessionId((current) => current === deletedId ? remaining[0]?.id ?? null : current);
    },
  });
  const send = useMutation({ mutationFn: (message: string) => startAgentExecution(sessionId!, { message, focus }), onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }) });
  const stop = useMutation({ mutationFn: () => cancelAgentExecution(latest!.id), onSuccess: () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] }) });
  const toolEvents = useMemo(
    () => live.events.filter(
      (event) => event.executionId === latest?.id && event.type.startsWith("agent.tool."),
    ),
    [latest?.id, live.events],
  );
  function confirmDelete(id: string, title: string) {
    const confirmed = window.confirm(
      `永久删除对话“${title}”及其中的历史消息？\n\n简历和已经确认的信息不会被删除。`,
    );
    if (confirmed) remove.mutate(id);
  }
  return <section className="profile-agent-workspace">
    <aside className="profile-agent-sessions" aria-label="对话记录">
      <header><div><strong>对话记录</strong><small>{sessions.data?.length ?? 0} 个</small></div><Button size="sm" variant="secondary" loading={create.isPending} onClick={() => create.mutate()} aria-label="新建对话"><MessageSquarePlus size={16} /></Button></header>
      <div>{sessions.data?.map((session) => <div className="profile-agent-session-row" key={session.id}>
        <button className={`profile-agent-session-select${session.id === sessionId ? " active" : ""}`} onClick={() => setSessionId(session.id)}><MessagesSquare size={16} /><span>{sessionTitle(session.title)}</span></button>
        <button
          className="profile-agent-session-delete"
          type="button"
          aria-label={`永久删除会话 ${sessionTitle(session.title)}`}
          title={session.id === sessionId && busy ? "请先停止当前任务" : "永久删除会话"}
          disabled={remove.isPending || (session.id === sessionId && busy)}
          onClick={() => confirmDelete(session.id, sessionTitle(session.title))}
        ><Trash2 size={15} /></button>
      </div>)}</div>
      {remove.isError ? <p className="profile-agent-session-error" role="alert">删除失败。若任务仍在运行，请先停止任务后重试。</p> : null}
    </aside>
    {sessionId ? <ProfileConversation workspaceId={workspaceId} messages={detail.data?.messages ?? []} events={toolEvents} streaming={streaming} executionStatus={executionStatus} streamAnswer={streamAnswer} busy={Boolean(busy || send.isPending || stop.isPending)} stopping={stop.isPending} onSend={(message) => send.mutate(message)} onStop={() => stop.mutate()} onChanged={() => client.invalidateQueries({ queryKey: ["agent-session", sessionId] })} /> : <div className="profile-agent-no-session"><MessagesSquare size={30} /><h2>开始使用简历助手</h2><p>它会根据你确认过的资料，检查信息是否完整、定位原文、发现冲突并整理简历表达。</p><Button loading={create.isPending} onClick={() => create.mutate()}>开始新对话</Button></div>}
    <details className="profile-agent-runtime">
      <summary>运行详情</summary>
      <dl><div><dt>参考范围</dt><dd>{focus.claimId ? "当前简历要点" : focus.materialVersionId ? "当前简历版本" : focus.materialId ? "当前简历" : "已确认信息"}</dd></div><div><dt>连接</dt><dd>{live.status === "connected" ? "正常" : "连接中"}</dd></div><div><dt>历史消息</dt><dd>{detail.data?.contextCompacted ? "已自动整理" : "完整"}</dd></div><div><dt>本次对话请求</dt><dd>{detail.data?.usage.callCount ?? 0} 次</dd></div></dl>
      {live.executionError ? <div role="alert">{live.executionError.message}</div> : null}{detail.isError ? <Button size="sm" variant="secondary" onClick={() => detail.refetch()}><RefreshCw size={14} />重新读取</Button> : null}
    </details>
  </section>;
}
