import { useEffect, useRef, useState } from "react";
import type { AgentEvent, AgentExecutionStatus, StreamingAssistantState } from "./agentTypes";

export type AgentEventConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(
    type: string,
    listener: (event: MessageEvent<string>) => void,
  ): void;
  close(): void;
}

interface UseAgentEventsOptions {
  createEventSource?: (url: string) => EventSourceLike;
  reconnectDelayMs?: number;
  sessionExists?: (sessionId: string) => Promise<boolean>;
  onMissingSession?: (sessionId: string) => void;
}

const EVENT_TYPES = [
  "session.created",
  "session.message.created",
  "curation.stage.changed",
  "curation.progress.changed",
  "curation.seed.changed",
  "curation.control.changed",
  "curation.summary.ready",
  "curation.command.resolved",
  "curation.command.interpreting",
  "execution.started",
  "execution.cancelling",
  "assistant.delta",
  "approval.required",
  "approval.resolved",
  "artifact.changed",
  "publication.changed",
  "execution.warning",
  "execution.interrupted",
  "execution.completed",
  "execution.failed",
  "execution.cancelled",
  "agent.tool.started",
  "agent.tool.completed",
  "agent.tool.failed",
  "review.round.started",
  "review.input.required",
  "review.input.resolved",
  "review.turn.responded",
  "review.answer.accepted",
  "review.evaluation.started",
  "review.evaluation.checking_key_points",
  "review.evaluation.deciding_follow_up",
  "review.evaluation.completed",
  "review.evaluation.failed",
  "review.attempt.completed",
  "review.progress.changed",
  "review.report.draft_created",
  "review.round.completed",
  "review.round.cancelled",
] as const;

const createBrowserEventSource = (url: string): EventSourceLike =>
  new EventSource(url);

async function defaultSessionExists(sessionId: string): Promise<boolean> {
  try {
    const response = await fetch(
      `/api/agent/sessions/${encodeURIComponent(sessionId)}`,
      { headers: { Accept: "application/json" } },
    );
    return ![204, 404, 410].includes(response.status);
  } catch {
    return true;
  }
}

export function useAgentEvents(
  sessionId: string | null,
  options: UseAgentEventsOptions = {},
) {
  const [status, setStatus] = useState<AgentEventConnectionStatus>("disconnected");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [executionError, setExecutionError] = useState<{ code: string; message: string } | null>(null);
  const [streamingByExecution, setStreamingByExecution] = useState<Record<string, StreamingAssistantState>>({});
  const [executionStateById, setExecutionStateById] = useState<Record<string, AgentExecutionStatus>>({});
  const cursorRef = useRef(0);
  const eventIdsRef = useRef(new Set<number>());
  const createEventSourceRef = useRef(
    options.createEventSource ?? createBrowserEventSource,
  );
  const reconnectDelayRef = useRef(options.reconnectDelayMs ?? 1000);
  const sessionExistsRef = useRef(
    options.sessionExists ??
      (options.createEventSource ? undefined : defaultSessionExists),
  );
  const onMissingSessionRef = useRef(options.onMissingSession);
  onMissingSessionRef.current = options.onMissingSession;

  useEffect(() => {
    cursorRef.current = 0;
    eventIdsRef.current = new Set();
    setEvents([]);
    setExecutionError(null);
    setStreamingByExecution({});
    setExecutionStateById({});
    if (!sessionId) {
      setStatus("disconnected");
      return;
    }

    let source: EventSourceLike | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const connect = async () => {
      const suffix = cursorRef.current > 0 ? `?after=${cursorRef.current}` : "";
      setStatus(cursorRef.current > 0 ? "reconnecting" : "connecting");
      if (sessionExistsRef.current) {
        const exists = await sessionExistsRef.current(sessionId);
        if (stopped) return;
        if (!exists) {
          setStatus("disconnected");
          onMissingSessionRef.current?.(sessionId);
          return;
        }
      }
      const nextSource = createEventSourceRef.current(
        `/api/agent/sessions/${sessionId}/events${suffix}`,
      );
      source = nextSource;
      nextSource.onopen = () => {
        if (!stopped && source === nextSource) setStatus("connected");
      };
      const receive = (message: MessageEvent<string>) => {
        if (stopped || source !== nextSource) return;
        let event: AgentEvent;
        try {
          event = JSON.parse(message.data) as AgentEvent;
        } catch {
          return;
        }
        if (!Number.isInteger(event.id) || event.id <= cursorRef.current || eventIdsRef.current.has(event.id)) return;
        eventIdsRef.current.add(event.id);
        cursorRef.current = Math.max(cursorRef.current, event.id);
        setEvents((current) => [...current, event].slice(-100));
        const executionId = event.executionId;
        if (executionId) {
          if (event.type === "assistant.delta") {
            const payload = event.payload as { text?: string };
            if (payload.text) {
              setStreamingByExecution((current) => ({
                ...current,
                [executionId]: {
                  text: `${current[executionId]?.text ?? ""}${payload.text}`,
                  status: "running",
                },
              }));
              setExecutionStateById((current) => ({ ...current, [executionId]: "running" }));
            }
          } else {
            const statusByEvent: Partial<Record<string, AgentExecutionStatus>> = {
              "execution.started": "running",
              "curation.command.interpreting": "running",
              "execution.cancelling": "cancelling",
              "execution.cancelled": "cancelled",
              "execution.interrupted": "interrupted",
              "execution.failed": "failed",
              "execution.completed": "completed",
            };
            const nextStatus = statusByEvent[event.type];
            if (nextStatus) {
              setExecutionStateById((current) => ({ ...current, [executionId]: nextStatus }));
              setStreamingByExecution((current) => {
                const existing = current[executionId];
                if (!existing && !["running", "cancelling"].includes(nextStatus)) return current;
                return {
                  ...current,
                  [executionId]: {
                    text: existing?.text ?? "",
                    status: nextStatus as StreamingAssistantState["status"],
                  },
                };
              });
            }
          }
        }
        if (event.type === "execution.started") {
          setExecutionError(null);
        } else if (event.type === "execution.failed") {
          const payload = event.payload as { code?: string; message?: string };
          setExecutionError({
            code: payload.code ?? "runtime_error",
            message: payload.message ?? "Agent 运行失败",
          });
        }
      };
      EVENT_TYPES.forEach((type) => nextSource.addEventListener(type, receive));
      nextSource.onerror = () => {
        if (stopped || source !== nextSource || timer !== null) return;
        nextSource.close();
        setStatus("reconnecting");
        timer = setTimeout(() => {
          timer = null;
          void connect();
        }, reconnectDelayRef.current);
      };
    };

    void connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [sessionId]);

  return { status, events, executionError, streamingByExecution, executionStateById };
}
