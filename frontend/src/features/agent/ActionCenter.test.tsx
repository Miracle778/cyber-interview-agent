import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionCenter } from "./ActionCenter";
import type { PendingAction } from "./hitlTypes";


const action: PendingAction = {
  id: "a1",
  workspaceId: "w1",
  sessionId: "s1",
  runId: "r1",
  actionType: "test.approval",
  preview: { summary: "original" },
  editableFields: ["summary"],
  status: "pending",
  version: 1,
  createdAt: "now",
  resolvedAt: null,
};


function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}


describe("ActionCenter", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("restores a pending action and submits an edited approval once", async () => {
    let resolveApproval: ((response: Response) => void) | undefined;
    const approval = new Promise<Response>((resolve) => {
      resolveApproval = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        const url = String(input);
        if (url.includes("/api/agent/actions?")) return Response.json([action]);
        if (url.endsWith("/approve") && init?.method === "POST") return approval;
        return Response.json([], { status: 200 });
      },
    );

    render(<ActionCenter workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("original")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("summary"), {
      target: { value: "edited" },
    });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    expect(screen.getByRole("button", { name: "批准" })).toBeDisabled();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith("/approve")),
      ).toBe(true),
    );
    const approveCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/approve"),
    );
    const body = JSON.parse(String(approveCall?.[1]?.body));
    expect(body.version).toBe(1);
    expect(body.editedPayload).toEqual({ summary: "edited" });
    expect(body.idempotencyKey).toMatch(/^approve-a1-/);

    resolveApproval?.(
      Response.json({
        ...action,
        preview: { summary: "edited" },
        status: "edited_and_approved",
        version: 2,
        resolvedAt: "later",
      }),
    );
    expect(await screen.findByText("确认动作已批准")).toBeInTheDocument();
  });

  it("requires a rejection reason and sends the decision", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        const url = String(input);
        if (url.includes("/api/agent/actions?")) return Response.json([action]);
        if (url.endsWith("/reject") && init?.method === "POST") {
          return Response.json({
            ...action,
            status: "rejected",
            version: 2,
            resolvedAt: "later",
          });
        }
        return Response.json([], { status: 200 });
      },
    );

    render(<ActionCenter workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("original")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));
    expect(await screen.findByText("请填写拒绝原因")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("拒绝原因"), {
      target: { value: "不继续" },
    });
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reject")),
      ).toBe(true),
    );
    const rejectCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/reject"),
    );
    expect(JSON.parse(String(rejectCall?.[1]?.body)).reason).toBe("不继续");
    expect(await screen.findByText("确认动作已拒绝")).toBeInTheDocument();
  });

  it("starts the real diagnostic graph and refreshes pending actions", async () => {
    let hasAction = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/api/agent/actions?")) {
        return Response.json(hasAction ? [action] : []);
      }
      if (url.includes("/api/agent/sessions?")) return Response.json([]);
      if (url === "/api/agent/sessions" && method === "POST") {
        return Response.json(
          {
            id: "s1",
            workspaceId: "w1",
            graphId: "test.approval",
            graphVersion: 1,
            title: "人工确认自检",
            status: "active",
            createdAt: "now",
            updatedAt: "now",
            lastRunId: null,
          },
          { status: 201 },
        );
      }
      if (url === "/api/agent/sessions/s1/runs" && method === "POST") {
        hasAction = true;
        return Response.json(
          {
            id: "r1",
            sessionId: "s1",
            status: "running",
            resumeCount: 0,
            errorCode: null,
            errorMessage: null,
            createdAt: "now",
            startedAt: "now",
            finishedAt: null,
          },
          { status: 202 },
        );
      }
      return Response.json({}, { status: 500 });
    });

    render(<ActionCenter workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("暂无待确认动作")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行确认测试" }));

    expect(await screen.findByText("original")).toBeInTheDocument();
  });

  it("waits for the action created by the diagnostic run", async () => {
    const oldAction = { ...action, id: "old", runId: "old-run", preview: { summary: "old" } };
    const newAction = { ...action, id: "new", runId: "new-run", preview: { summary: "new" } };
    let actionReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/api/agent/actions?")) {
        actionReads += 1;
        return Response.json(actionReads < 3 ? [oldAction] : [oldAction, newAction]);
      }
      if (url.includes("/api/agent/sessions?")) return Response.json([]);
      if (url === "/api/agent/sessions" && method === "POST") {
        return Response.json({
          id: "s1", workspaceId: "w1", graphId: "test.approval", graphVersion: 1,
          title: "人工确认自检", status: "active", createdAt: "now", updatedAt: "now",
          lastRunId: null,
        }, { status: 201 });
      }
      if (url === "/api/agent/sessions/s1/runs" && method === "POST") {
        return Response.json({
          id: "new-run", sessionId: "s1", status: "running", resumeCount: 0,
          errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now",
          finishedAt: null,
        }, { status: 202 });
      }
      return Response.json({}, { status: 500 });
    });

    render(<ActionCenter workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("old")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行确认测试" }));

    expect(await screen.findByText("new")).toBeInTheDocument();
    expect(actionReads).toBeGreaterThanOrEqual(3);
  });

  it("uses a new idempotency key after approval content changes", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/agent/actions?")) return Response.json([action]);
      if (url.endsWith("/approve") && init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        return Response.json(
          { code: "temporary", message: "暂时失败" },
          { status: 503 },
        );
      }
      return Response.json([], { status: 200 });
    });

    render(<ActionCenter workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("original")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    expect(await screen.findByText("暂时失败")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("summary"), {
      target: { value: "changed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(bodies).toHaveLength(2));

    expect(bodies[0].idempotencyKey).not.toBe(bodies[1].idempotencyKey);
  });
});
