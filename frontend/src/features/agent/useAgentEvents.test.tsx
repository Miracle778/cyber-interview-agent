import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAgentEvents, type EventSourceLike } from "./useAgentEvents";

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent<string>) => void>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close = vi.fn();

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener);
  }

  emit(event: object) {
    const type = (event as { type: string }).type;
    this.listeners.get(type)?.({ data: JSON.stringify(event) } as MessageEvent<string>);
  }
}

describe("useAgentEvents", () => {
  afterEach(() => {
    FakeEventSource.instances = [];
    vi.useRealTimers();
  });

  it("deduplicates events and reconnects from the last persisted id", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useAgentEvents("s1", {
        createEventSource: (url) => new FakeEventSource(url),
        reconnectDelayMs: 10,
      }),
    );

    const first = FakeEventSource.instances[0];
    act(() => first.onopen?.(new Event("open")));
    act(() => {
      first.emit({
        id: 4,
        type: "assistant.delta",
        sessionId: "s1",
        executionId: "r1",
        timestamp: "now",
        payload: { messageId: "m1", content: "hello" },
      });
      first.emit({
        id: 4,
        type: "assistant.delta",
        sessionId: "s1",
        executionId: "r1",
        timestamp: "now",
        payload: { messageId: "m1", content: "hello" },
      });
      first.onerror?.(new Event("error"));
      first.onerror?.(new Event("error"));
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.status).toBe("reconnecting");
    act(() => vi.advanceTimersByTime(10));
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toBe(
      "/api/agent/sessions/s1/events?after=4",
    );
    const second = FakeEventSource.instances[1];
    act(() => {
      first.onerror?.(new Event("error"));
      vi.advanceTimersByTime(10);
    });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(second.close).not.toHaveBeenCalled();
  });

  it("keeps prior events when an execution fails", () => {
    const { result } = renderHook(() =>
      useAgentEvents("s1", {
        createEventSource: (url) => new FakeEventSource(url),
      }),
    );
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emit({ id: 1, type: "execution.started", sessionId: "s1", executionId: "r1", timestamp: "now", payload: {} });
      source.emit({ id: 2, type: "execution.failed", sessionId: "s1", executionId: "r1", timestamp: "now", payload: { code: "runtime_error", message: "failed" } });
    });

    expect(result.current.events.map((event) => event.type)).toEqual([
      "execution.started",
      "execution.failed",
    ]);
    expect(result.current.executionError).toEqual({
      code: "runtime_error",
      message: "failed",
    });
  });

  it("clears a replayed failure when a newer execution starts", () => {
    const { result } = renderHook(() =>
      useAgentEvents("s1", {
        createEventSource: (url) => new FakeEventSource(url),
      }),
    );
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emit({ id: 1, type: "execution.failed", sessionId: "s1", executionId: "r1", timestamp: "now", payload: { code: "runtime_error" } });
      source.emit({ id: 2, type: "execution.started", sessionId: "s1", executionId: "r2", timestamp: "now", payload: {} });
      source.emit({ id: 3, type: "execution.interrupted", sessionId: "s1", executionId: "r2", timestamp: "now", payload: {} });
    });

    expect(result.current.executionError).toBeNull();
  });

  it("does not open or retry an event stream for a missing session", async () => {
    vi.useFakeTimers();
    const onMissingSession = vi.fn();
    const { result } = renderHook(() =>
      useAgentEvents("missing-session", {
        createEventSource: (url) => new FakeEventSource(url),
        reconnectDelayMs: 10,
        sessionExists: async () => false,
        onMissingSession,
      }),
    );

    await act(async () => {});
    act(() => vi.advanceTimersByTime(100));

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(onMissingSession).toHaveBeenCalledWith("missing-session");
    expect(result.current.status).toBe("disconnected");
  });
});
