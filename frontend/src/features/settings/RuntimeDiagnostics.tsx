import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, Play } from "lucide-react";
import {
  createAgentSession,
  getAgentSession,
  listAgentSessions,
  startAgentExecution,
} from "../agent/agentApi";
import type { AgentEvent, AgentExecution } from "../agent/agentTypes";
import { useAgentEvents } from "../agent/useAgentEvents";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { formatBeijingTime } from "../../shared/time";

const DIAGNOSTIC_KIND = "diagnostic.echo";
const DIAGNOSTIC_TITLE = "Agent Runtime 自检";

const EVENT_LABELS: Record<string, string> = {
  "session.created": "自检会话已创建",
  "execution.started": "运行已启动",
  "assistant.delta": "Echo 响应已保存",
  "execution.completed": "运行完成",
  "execution.failed": "运行失败",
  "execution.cancelled": "运行已取消",
  "execution.interrupted": "运行被中断",
};

function runState(run: AgentExecution | null, events: AgentEvent[]) {
  const terminalEvent = [...events]
    .reverse()
    .find((event) => ["execution.completed", "execution.failed", "execution.cancelled", "execution.interrupted"].includes(event.type));
  const status = terminalEvent?.type.replace("execution.", "") ?? run?.status;
  if (status === "completed") return { label: "自检完成", tone: "success" as const };
  if (status === "failed") return { label: "自检失败", tone: "danger" as const };
  if (status === "interrupted") return { label: "自检中断", tone: "warning" as const };
  if (status === "cancelled") return { label: "自检已取消", tone: "warning" as const };
  if (status === "queued" || status === "running") return { label: "自检运行中", tone: "primary" as const };
  return { label: "Runtime 已就绪，可以运行自检", tone: "success" as const };
}

export function RuntimeDiagnostics({ workspaceId }: { workspaceId: string }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeExecution, setActiveExecution] = useState<AgentExecution | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const sessionsQuery = useQuery({
    queryKey: ["agent-sessions", workspaceId],
    queryFn: () => listAgentSessions(workspaceId),
  });

  const restoredSession = useMemo(
    () =>
      sessionsQuery.data?.find(
        (session) =>
          session.kind === DIAGNOSTIC_KIND,
      ) ?? null,
    [sessionsQuery.data],
  );

  useEffect(() => {
    if (!sessionId && restoredSession) setSessionId(restoredSession.id);
  }, [restoredSession, sessionId]);

  const detailQuery = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => getAgentSession(sessionId as string),
    enabled: sessionId !== null,
  });
  const stream = useAgentEvents(sessionId, {
    onMissingSession: (missingSessionId) => {
      setSessionId((current) => (current === missingSessionId ? null : current));
      setActiveExecution(null);
      void sessionsQuery.refetch();
    },
  });
  const latestExecution = activeExecution ?? detailQuery.data?.latestExecution ?? null;
  const currentExecutionEvents = useMemo(
    () =>
      latestExecution
        ? stream.events.filter((event) => event.executionId === latestExecution.id)
        : stream.events,
    [latestExecution?.id, stream.events],
  );

  useEffect(() => {
    const hasTerminalEvent = currentExecutionEvents.some((event) =>
      ["execution.completed", "execution.failed", "execution.cancelled", "execution.interrupted"].includes(event.type),
    );
    if (hasTerminalEvent) void detailQuery.refetch();
  }, [currentExecutionEvents, detailQuery.refetch]);

  const runMutation = useMutation({
    mutationFn: async () => {
      let targetSessionId = sessionId ?? restoredSession?.id ?? null;
      if (!targetSessionId) {
        const session = await createAgentSession({
          workspaceId,
          kind: DIAGNOSTIC_KIND,
          title: DIAGNOSTIC_TITLE,
        });
        targetSessionId = session.id;
        setSessionId(session.id);
      }
      return startAgentExecution(targetSessionId, { text: "runtime-check" });
    },
    onMutate: () => setCommandError(null),
    onSuccess: (execution) => setActiveExecution(execution),
    onError: (error) =>
      setCommandError(error instanceof Error ? error.message : "无法启动 Runtime 自检"),
  });

  const state = runState(latestExecution, currentExecutionEvents);
  const failed = state.label === "自检失败";
  const hasTerminalEvent = currentExecutionEvents.some((event) =>
    ["execution.completed", "execution.failed", "execution.cancelled", "execution.interrupted"].includes(
      event.type,
    ),
  );
  const visibleEvents = stream.events.filter(
    (event) =>
      EVENT_LABELS[event.type] &&
      (event.type === "session.created" || event.executionId === latestExecution?.id),
  );
  const connectionLabel =
    stream.status === "connected"
      ? "SSE 已连接"
      : stream.status === "reconnecting"
        ? "SSE 正在重连"
        : stream.status === "connecting"
          ? "SSE 正在连接"
          : "SSE 未连接";

  return (
    <Card
      title="Agent Runtime"
      icon={<Activity size={18} />}
      actions={
        <Button
          size="sm"
          onClick={() => runMutation.mutate()}
          loading={runMutation.isPending}
          disabled={
            !hasTerminalEvent &&
            latestExecution?.status === "running"
          }
        >
          <Play size={15} aria-hidden="true" />
          运行自检
        </Button>
      }
    >
      <div className="runtime-diagnostics" aria-live="polite">
        <div className="runtime-diagnostics__status">
          <Badge tone={state.tone} dot>{state.label}</Badge>
          <Badge tone={stream.status === "connected" ? "success" : "neutral"} dot>
            {connectionLabel}
          </Badge>
        </div>

        {sessionsQuery.isLoading ? <p className="status-note">正在读取 Runtime 状态…</p> : null}
        {failed ? <p className="status-note status-note--warning">请检查后端日志与模型配置后重试</p> : null}
        {commandError ? <p className="status-note status-note--warning">{commandError}</p> : null}

        {visibleEvents.length > 0 ? (
          <ol className="runtime-timeline" aria-label="Runtime 事件">
            {visibleEvents.map((event) => (
              <li key={event.id} className="runtime-timeline__item">
                <span>{EVENT_LABELS[event.type]}</span>
                <time>{formatBeijingTime(event.timestamp) ?? event.timestamp}</time>
              </li>
            ))}
          </ol>
        ) : (
          <p className="status-note">运行一次自检可验证 Session、Checkpoint 与事件流。</p>
        )}
      </div>
    </Card>
  );
}
