import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, ShieldCheck } from "lucide-react";
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

const KIND = "diagnostic.security";
const SESSION_TITLE = "工具安全自检";
const TERMINAL_TYPES = [
  "execution.completed",
  "execution.failed",
  "execution.cancelled",
  "execution.interrupted",
];

function hasTerminalEvent(events: AgentEvent[]) {
  return events.some((event) => TERMINAL_TYPES.includes(event.type));
}

function statusFor(run: AgentExecution | null, events: AgentEvent[], checksPassed: boolean) {
  const terminal = [...events].reverse().find((event) => TERMINAL_TYPES.includes(event.type));
  const status = terminal?.type.replace("execution.", "") ?? run?.status;
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
  const [activeExecution, setActiveExecution] = useState<AgentExecution | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const sessionsQuery = useQuery({
    queryKey: ["agent-sessions", workspaceId],
    queryFn: () => listAgentSessions(workspaceId),
  });
  const restoredSession = useMemo(
    () =>
      sessionsQuery.data?.find(
        (session) => session.kind === KIND,
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
    if (hasTerminalEvent(currentExecutionEvents)) void detailQuery.refetch();
  }, [currentExecutionEvents, detailQuery.refetch]);

  const diagnosticResult = detailQuery.data?.messages
    .filter((message) => message.role === "assistant")
    .at(-1)?.content ?? "";
  const checks = [
    {
      label: "授权读取通过",
      passed: diagnosticResult.includes("授权读取通过"),
    },
    {
      label: "未注册工具已拒绝",
      passed: diagnosticResult.includes("未注册工具已拒绝"),
    },
    {
      label: "未授权 Scope 已拒绝",
      passed: diagnosticResult.includes("未授权 Scope 已拒绝"),
    },
    {
      label: "路径越界已拒绝",
      passed: diagnosticResult.includes("路径越界已拒绝"),
    },
  ];
  const checksPassed = checks.every((check) => check.passed);
  const state = statusFor(latestExecution, currentExecutionEvents, checksPassed);
  const terminal = hasTerminalEvent(currentExecutionEvents);
  const failed = state.tone === "danger";

  const runMutation = useMutation({
    mutationFn: async () => {
      let targetSessionId = sessionId ?? restoredSession?.id ?? null;
      if (!targetSessionId) {
        const session = await createAgentSession({
          workspaceId,
          kind: KIND,
          title: SESSION_TITLE,
        });
        targetSessionId = session.id;
        setSessionId(session.id);
      }
      return startAgentExecution(targetSessionId, {});
    },
    onMutate: () => setCommandError(null),
    onSuccess: (execution) => setActiveExecution(execution),
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
            !terminal && latestExecution?.status === "running"
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

      </div>
    </Card>
  );
}
