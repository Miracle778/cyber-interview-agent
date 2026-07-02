import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockEventSource } from "../test/setup";
import { useRunEvents } from "./useRunEvents";

describe("useRunEvents", () => {
  afterEach(() => {
    MockEventSource.reset();
    vi.restoreAllMocks();
  });

  it("collects events and closes on terminal event", () => {
    const { result, unmount } = renderHook(() => useRunEvents("run-1"));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit("delta", {
        run_id: "run-1",
        sequence: 1,
        event_type: "delta",
        payload: { text: "a" },
      });
      source.emit("completed", {
        run_id: "run-1",
        sequence: 2,
        event_type: "completed",
        payload: {},
      });
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.terminal).toBe("completed");
    expect(source.closed).toBe(true);

    unmount();
  });
});
