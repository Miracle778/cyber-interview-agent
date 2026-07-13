import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cancelAgentExecution,
  createAgentSession,
  getAgentSession,
  listAgentSessions,
  startAgentExecution,
} from "./agentApi";

describe("agentApi", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses the product session and execution endpoints", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => Response.json({ id: "resource-1" }));

    await createAgentSession({
      workspaceId: "w 1",
      kind: "diagnostic.echo",
      title: "Agent Runtime 自检",
    });
    await listAgentSessions("w 1");
    await getAgentSession("s1");
    await startAgentExecution("s1", { text: "hello" });
    await cancelAgentExecution("e1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/agent/sessions?workspaceId=w%201",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/agent/sessions",
      "/api/agent/sessions?workspaceId=w%201",
      "/api/agent/sessions/s1",
      "/api/agent/sessions/s1/executions",
      "/api/agent/executions/e1/cancel",
    ]);
  });
});
