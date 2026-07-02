import { useEffect, useRef, useState } from "react";

export interface RunEvent {
  run_id: string;
  sequence: number;
  event_type: "delta" | "partial" | "completed" | "failed";
  payload: unknown;
}

export function useRunEvents(runId: string | null) {
  const [state, setState] = useState<{
    runId: string | null;
    events: RunEvent[];
    terminal: "completed" | "failed" | null;
  }>({ runId: null, events: [], terminal: null });
  const seenSequences = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!runId) {
      return;
    }
    seenSequences.current = new Set();
    const source = new EventSource(`/api/profile/runs/${runId}/events`);

    const addEvent = (event: RunEvent) => {
      setState((previous) => {
        if (seenSequences.current.has(event.sequence)) {
          return previous;
        }
        seenSequences.current.add(event.sequence);
        const previousEvents = previous.runId === runId ? previous.events : [];
        return { runId, events: [...previousEvents, event], terminal: previous.terminal };
      });
    };

    source.addEventListener("delta", (event: MessageEvent) => {
      addEvent(JSON.parse(event.data) as RunEvent);
    });

    const onTerminal = (event: MessageEvent) => {
      const parsed = JSON.parse(event.data) as RunEvent;
      addEvent(parsed);
      setState((previous) => ({
        runId,
        events: previous.runId === runId ? previous.events : [],
        terminal: parsed.event_type as "completed" | "failed",
      }));
      source.close();
    };

    source.addEventListener("completed", onTerminal);
    source.addEventListener("failed", onTerminal);
    source.onerror = () => {
      fetch(`/api/profile/runs/${runId}`).then((response) => {
        if (response.status === 404) {
          source.close();
        }
      });
    };

    return () => source.close();
  }, [runId]);

  if (state.runId !== runId) {
    return { events: [], terminal: null };
  }
  return { events: state.events, terminal: state.terminal };
}
