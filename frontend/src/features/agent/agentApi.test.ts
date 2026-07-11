import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cancelAgentRun,
  createAgentSession,
  getAgentSession,
  listAgentSessions,
  resumeAgentRun,
  startAgentRun,
} from "./agentApi";

describe("agentApi", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses the persistent session and run endpoints", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => Response.json({ id: "resource-1" }));

    await createAgentSession({
      workspaceId: "w 1",
      graphId: "test.echo",
      graphVersion: 1,
      title: "Agent Runtime 自检",
    });
    await listAgentSessions("w 1");
    await getAgentSession("s1");
    await startAgentRun("s1", { text: "hello" });
    await resumeAgentRun("r1");
    await cancelAgentRun("r1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/agent/sessions?workspaceId=w%201",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/agent/sessions",
      "/api/agent/sessions?workspaceId=w%201",
      "/api/agent/sessions/s1",
      "/api/agent/sessions/s1/runs",
      "/api/agent/runs/r1/resume",
      "/api/agent/runs/r1/cancel",
    ]);
  });
});
