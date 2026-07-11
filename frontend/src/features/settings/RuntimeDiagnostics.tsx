import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, Play } from "lucide-react";
import {
  createAgentSession,
  getAgentSession,
  listAgentSessions,
  startAgentRun,
} from "../agent/agentApi";
import type { AgentEvent, AgentRun } from "../agent/agentTypes";
import { useAgentEvents } from "../agent/useAgentEvents";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";

const DIAGNOSTIC_GRAPH_ID = "test.echo";
const DIAGNOSTIC_TITLE = "Agent Runtime 自检";

const EVENT_LABELS: Record<string, string> = {
  "session.created": "自检会话已创建",
  "run.started": "运行已启动",
  "message.completed": "Echo 响应已保存",
  "run.completed": "运行完成",
  "run.failed": "运行失败",
  "run.cancelled": "运行已取消",
  "run.interrupted": "运行被中断",
};

function runState(run: AgentRun | null, events: AgentEvent[]) {
  const terminalEvent = [...events]
    .reverse()
    .find((event) => ["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(event.type));
  const status = terminalEvent?.type.replace("run.", "") ?? run?.status;
  if (status === "completed") return { label: "自检完成", tone: "success" as const };
  if (status === "failed") return { label: "自检失败", tone: "danger" as const };
  if (status === "interrupted") return { label: "自检中断", tone: "warning" as const };
  if (status === "cancelled") return { label: "自检已取消", tone: "warning" as const };
  if (status === "queued" || status === "running") return { label: "自检运行中", tone: "primary" as const };
  return { label: "Runtime 已就绪，可以运行自检", tone: "success" as const };
}

export function RuntimeDiagnostics({ workspaceId }: { workspaceId: string }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const sessionsQuery = useQuery({
    queryKey: ["agent-sessions", workspaceId],
    queryFn: () => listAgentSessions(workspaceId),
  });

  const restoredSession = useMemo(
    () =>
      sessionsQuery.data?.find(
        (session) =>
          session.graphId === DIAGNOSTIC_GRAPH_ID && session.graphVersion === 1,
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
  const stream = useAgentEvents(sessionId);
  const latestRun = activeRun ?? detailQuery.data?.latestRun ?? null;
  const currentRunEvents = useMemo(
    () =>
      latestRun
        ? stream.events.filter((event) => event.runId === latestRun.id)
        : stream.events,
    [latestRun?.id, stream.events],
  );

  useEffect(() => {
    const hasTerminalEvent = currentRunEvents.some((event) =>
      ["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(event.type),
    );
    if (hasTerminalEvent) void detailQuery.refetch();
  }, [currentRunEvents, detailQuery.refetch]);

  const runMutation = useMutation({
    mutationFn: async () => {
      let targetSessionId = sessionId ?? restoredSession?.id ?? null;
      if (!targetSessionId) {
        const session = await createAgentSession({
          workspaceId,
          graphId: DIAGNOSTIC_GRAPH_ID,
          graphVersion: 1,
          title: DIAGNOSTIC_TITLE,
        });
        targetSessionId = session.id;
        setSessionId(session.id);
      }
      return startAgentRun(targetSessionId, { text: "runtime-check" });
    },
    onMutate: () => setCommandError(null),
    onSuccess: (run) => setActiveRun(run),
    onError: (error) =>
      setCommandError(error instanceof Error ? error.message : "无法启动 Runtime 自检"),
  });

  const state = runState(latestRun, currentRunEvents);
  const failed = state.label === "自检失败";
  const hasTerminalEvent = currentRunEvents.some((event) =>
    ["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(
      event.type,
    ),
  );
  const visibleEvents = stream.events.filter(
    (event) =>
      EVENT_LABELS[event.type] &&
      (event.type === "session.created" || event.runId === latestRun?.id),
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
            (latestRun?.status === "queued" || latestRun?.status === "running")
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
                <time>{event.timestamp}</time>
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
