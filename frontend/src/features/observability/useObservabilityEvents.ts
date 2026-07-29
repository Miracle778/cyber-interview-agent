import { useEffect, useRef, useState } from "react";
import {
  executionChangedEventSchema,
  type ExecutionSummary,
} from "./observabilityTypes";


export type ObservabilityConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

export function useObservabilityEvents(
  workspaceId: string | null,
  onExecutionChanged: (execution: ExecutionSummary) => void,
) {
  const [status, setStatus] =
    useState<ObservabilityConnectionStatus>("disconnected");
  const cursorRef = useRef(0);
  const callbackRef = useRef(onExecutionChanged);
  callbackRef.current = onExecutionChanged;

  useEffect(() => {
    cursorRef.current = 0;
    if (!workspaceId || typeof EventSource === "undefined") {
      setStatus("disconnected");
      return;
    }

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const connect = () => {
      const query = new URLSearchParams({ workspaceId });
      if (cursorRef.current > 0) {
        query.set("afterEventId", String(cursorRef.current));
      }
      setStatus(cursorRef.current > 0 ? "reconnecting" : "connecting");
      const nextSource = new EventSource(
        `/api/agent-observability/events?${query.toString()}`,
      );
      source = nextSource;
      nextSource.onopen = () => {
        if (!stopped && source === nextSource) setStatus("connected");
      };
      nextSource.addEventListener(
        "execution.summary.changed",
        (message: MessageEvent<string>) => {
          if (stopped || source !== nextSource) return;
          try {
            const event = executionChangedEventSchema.parse(
              JSON.parse(message.data),
            );
            const eventId = Number(event.eventId);
            if (eventId <= cursorRef.current) return;
            cursorRef.current = eventId;
            callbackRef.current(event.execution);
          } catch {
            // Malformed live events are ignored; the next snapshot remains
            // authoritative and prevents fabricated zero-value summaries.
          }
        },
      );
      nextSource.onerror = () => {
        if (stopped || source !== nextSource || reconnectTimer) return;
        nextSource.close();
        setStatus("reconnecting");
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, 1000);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
    };
  }, [workspaceId]);

  return status;
}
