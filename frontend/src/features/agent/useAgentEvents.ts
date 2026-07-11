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
  "run.started",
  "graph.node.started",
  "graph.node.completed",
  "message.delta",
  "message.completed",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "hitl.required",
  "hitl.resolved",
  "draft.created",
  "publication.started",
  "publication.completed",
  "publication.index_stale",
  "run.interrupted",
  "run.completed",
  "run.failed",
  "run.cancelled",
] as const;

const createBrowserEventSource = (url: string): EventSourceLike =>
  new EventSource(url);

export function useAgentEvents(
  sessionId: string | null,
  options: UseAgentEventsOptions = {},
) {
  const [status, setStatus] = useState<AgentEventConnectionStatus>("disconnected");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [runError, setRunError] = useState<{ code: string; message: string } | null>(null);
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
    setRunError(null);
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
      source = createEventSourceRef.current(
        `/api/agent/sessions/${sessionId}/events${suffix}`,
      );
      source.onopen = () => setStatus("connected");
      const receive = (message: MessageEvent<string>) => {
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
        if (event.type === "run.failed") {
          const payload = event.payload as { code?: string; message?: string };
          setRunError({
            code: payload.code ?? "runtime_error",
            message: payload.message ?? "Agent 运行失败",
          });
        }
      };
      EVENT_TYPES.forEach((type) => source?.addEventListener(type, receive));
      source.onerror = () => {
        source?.close();
        if (stopped) return;
        setStatus("reconnecting");
        timer = setTimeout(connect, reconnectDelayRef.current);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [sessionId]);

  return { status, events, runError };
}
