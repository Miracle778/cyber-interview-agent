import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, ShieldCheck } from "lucide-react";
import {
  createAgentSession,
  getAgentSession,
  listAgentSessions,
  startAgentRun,
} from "../agent/agentApi";
import type { AgentEvent, AgentRun, ToolEventPayload } from "../agent/agentTypes";
import { useAgentEvents } from "../agent/useAgentEvents";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";

const GRAPH_ID = "test.tool-security";
const GRAPH_VERSION = 1;
const SESSION_TITLE = "工具安全自检";
const TERMINAL_TYPES = [
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.interrupted",
];

function payloadOf(event: AgentEvent): ToolEventPayload {
  return event.payload as ToolEventPayload;
}

function hasTerminalEvent(events: AgentEvent[]) {
  return events.some((event) => TERMINAL_TYPES.includes(event.type));
}

function statusFor(run: AgentRun | null, events: AgentEvent[], checksPassed: boolean) {
  const terminal = [...events].reverse().find((event) => TERMINAL_TYPES.includes(event.type));
  const status = terminal?.type.replace("run.", "") ?? run?.status;
  if (status === "failed") return { label: "工具安全自检失败", tone: "danger" as const };
  if (status === "cancelled" || status === "interrupted") {
    return { label: "工具安全自检未完成", tone: "warning" as const };
  }
  if (status === "completed" && checksPassed) {
    return { label: "工具安全自检通过", tone: "success" as const };
  }
  if (status === "completed") return { label: "正在恢复检查结果", tone: "primary" as const };
  if (status === "queued" || status === "running") {
    return { label: "工具安全自检运行中", tone: "primary" as const };
  }
  return { label: "工具安全策略已就绪", tone: "success" as const };
}

export function SecurityDiagnostics({ workspaceId }: { workspaceId: string }) {
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
        (session) => session.graphId === GRAPH_ID && session.graphVersion === GRAPH_VERSION,
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
    if (hasTerminalEvent(currentRunEvents)) void detailQuery.refetch();
  }, [currentRunEvents, detailQuery.refetch]);

  const toolEvents = currentRunEvents.filter((event) =>
    ["tool.completed", "tool.failed"].includes(event.type),
  );
  const checks = [
    {
      label: "授权读取通过",
      passed: toolEvents.some(
        (event) =>
          event.type === "tool.completed" &&
          payloadOf(event).toolName === "diagnostic_read" &&
          payloadOf(event).resourcePath === "probe.txt",
      ),
    },
    {
      label: "未注册工具已拒绝",
      passed: toolEvents.some(
        (event) => event.type === "tool.failed" && payloadOf(event).code === "tool_not_allowed",
      ),
    },
    {
      label: "未授权 Scope 已拒绝",
      passed: toolEvents.some(
        (event) => event.type === "tool.failed" && payloadOf(event).code === "tool_scope_denied",
      ),
    },
    {
      label: "路径越界已拒绝",
      passed: toolEvents.some(
        (event) => event.type === "tool.failed" && payloadOf(event).code === "workspace_path_denied",
      ),
    },
  ];
  const checksPassed = checks.every((check) => check.passed);
  const state = statusFor(latestRun, currentRunEvents, checksPassed);
  const terminal = hasTerminalEvent(currentRunEvents);
  const failed = state.tone === "danger";

  const runMutation = useMutation({
    mutationFn: async () => {
      let targetSessionId = sessionId ?? restoredSession?.id ?? null;
      if (!targetSessionId) {
        const session = await createAgentSession({
          workspaceId,
          graphId: GRAPH_ID,
          graphVersion: GRAPH_VERSION,
          title: SESSION_TITLE,
        });
        targetSessionId = session.id;
        setSessionId(session.id);
      }
      return startAgentRun(targetSessionId, {});
    },
    onMutate: () => setCommandError(null),
    onSuccess: (run) => setActiveRun(run),
    onError: (error) =>
      setCommandError(error instanceof Error ? error.message : "无法启动工具安全自检"),
  });

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
      title="工具安全"
      icon={<ShieldCheck size={18} />}
      actions={
        <Button
          size="sm"
          onClick={() => runMutation.mutate()}
          loading={runMutation.isPending}
          disabled={
            !terminal && (latestRun?.status === "queued" || latestRun?.status === "running")
          }
        >
          <Play size={15} aria-hidden="true" />
          运行安全自检
        </Button>
      }
    >
      <div className="security-diagnostics" aria-live="polite">
        <div className="runtime-diagnostics__status">
          <Badge tone={state.tone} dot>{state.label}</Badge>
          <Badge tone={stream.status === "connected" ? "success" : "neutral"} dot>
            {connectionLabel}
          </Badge>
        </div>

        {sessionsQuery.isLoading ? <p className="status-note">正在读取工具安全状态…</p> : null}
        {failed ? <p className="status-note status-note--warning">请检查后端工具审计记录后重试</p> : null}
        {commandError ? <p className="status-note status-note--warning">{commandError}</p> : null}

        <ul className="security-checks" aria-label="工具安全检查结果">
          {checks.map((check) => (
            <li key={check.label} className="security-checks__item">
              <span>{check.label}</span>
              <Badge tone={check.passed ? "success" : "neutral"}>
                {check.passed ? "通过" : "待检查"}
              </Badge>
            </li>
          ))}
        </ul>

        {toolEvents.length > 0 ? (
          <ol className="runtime-timeline" aria-label="工具安全事件">
            {toolEvents.map((event) => {
              const payload = payloadOf(event);
              const detail = payload.code ?? "completed";
              const resource = payload.resourcePath ? ` · ${payload.resourcePath}` : "";
              return (
                <li key={event.id} className="runtime-timeline__item">
                  <span>{payload.toolName ?? "tool"} · {detail}{resource}</span>
                  <time>{event.timestamp}</time>
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </Card>
  );
}
