import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "./agentTypes";

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
}

const EVENT_TYPES = [
  "session.created",
  "execution.started",
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
] as const;

const createBrowserEventSource = (url: string): EventSourceLike =>
  new EventSource(url);

export function useAgentEvents(
  sessionId: string | null,
  options: UseAgentEventsOptions = {},
) {
  const [status, setStatus] = useState<AgentEventConnectionStatus>("disconnected");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [executionError, setExecutionError] = useState<{ code: string; message: string } | null>(null);
  const cursorRef = useRef(0);
  const eventIdsRef = useRef(new Set<number>());
  const createEventSourceRef = useRef(
    options.createEventSource ?? createBrowserEventSource,
  );
  const reconnectDelayRef = useRef(options.reconnectDelayMs ?? 1000);

  useEffect(() => {
    cursorRef.current = 0;
    eventIdsRef.current = new Set();
    setEvents([]);
    setExecutionError(null);
    if (!sessionId) {
      setStatus("disconnected");
      return;
    }

    let source: EventSourceLike | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const connect = () => {
      const suffix = cursorRef.current > 0 ? `?after=${cursorRef.current}` : "";
      setStatus(cursorRef.current > 0 ? "reconnecting" : "connecting");
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
        if (!Number.isInteger(event.id) || eventIdsRef.current.has(event.id)) return;
        eventIdsRef.current.add(event.id);
        cursorRef.current = Math.max(cursorRef.current, event.id);
        setEvents((current) => [...current, event]);
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
          connect();
        }, reconnectDelayRef.current);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [sessionId]);

  return { status, events, executionError };
}
