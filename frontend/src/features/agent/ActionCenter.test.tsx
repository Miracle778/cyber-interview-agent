import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionCenter } from "./ActionCenter";
import type { PendingAction } from "./hitlTypes";


const action: PendingAction = {
  id: "a1",
  workspaceId: "w1",
  sessionId: "s1",
  executionId: "r1",
  actionType: "diagnostic.approval",
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
    const onResolved = vi.fn();
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

    render(<ActionCenter workspaceId="w1" onResolved={onResolved} />, { wrapper });
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
    expect(onResolved).toHaveBeenCalledOnce();
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
            kind: "diagnostic.approval",

            title: "人工确认自检",
            status: "active",
            createdAt: "now",
            updatedAt: "now",
            latestExecutionId: null,
          },
          { status: 201 },
        );
      }
      if (url === "/api/agent/sessions/s1/executions" && method === "POST") {
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
    const oldAction = { ...action, id: "old", executionId: "old-run", preview: { summary: "old" } };
    const newAction = { ...action, id: "new", executionId: "new-run", preview: { summary: "new" } };
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
          id: "s1", workspaceId: "w1", kind: "diagnostic.approval",
          title: "人工确认自检", status: "active", createdAt: "now", updatedAt: "now",
          latestExecutionId: null,
        }, { status: 201 });
      }
      if (url === "/api/agent/sessions/s1/executions" && method === "POST") {
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

  it("hides the diagnostic button when showDiagnostic is false", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/agent/actions?")) return Response.json([action]);
      return Response.json([], { status: 200 });
    });

    render(<ActionCenter workspaceId="w1" showDiagnostic={false} />, { wrapper });
    expect(await screen.findByText("original")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "运行确认测试" })).toBeNull();
    // approve/reject controls remain available for existing pending actions
    expect(screen.getByRole("button", { name: "批准" })).toBeInTheDocument();
  });

  it("renders nothing when a non-diagnostic consumer has no pending action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json([], { status: 200 }),
    );

    const { container } = render(
      <ActionCenter
        workspaceId="w1"
        showDiagnostic={false}
        actionType="knowledge.publish"
      />,
      { wrapper },
    );

    expect(container).toBeEmptyDOMElement();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("filters the list to the requested action type", async () => {
    const publishAction: PendingAction = {
      ...action,
      id: "pub1",
      executionId: "pub-run",
      actionType: "knowledge.publish",
      preview: { title: "缓存穿透" },
      editableFields: ["title", "markdown"],
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/agent/actions?")) {
        return Response.json([action, publishAction]);
      }
      return Response.json([], { status: 200 });
    });

    render(
      <ActionCenter workspaceId="w1" actionType="knowledge.publish" />,
      { wrapper },
    );
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    // the test.approval action is filtered out
    expect(screen.queryByText("original")).toBeNull();
  });

  it("watches the run returned by publish-request until its action appears", async () => {
    const publishAction: PendingAction = {
      ...action,
      id: "pub1",
      executionId: "publish-run",
      actionType: "knowledge.publish",
      preview: { title: "缓存穿透" },
      editableFields: ["title", "markdown"],
    };
    let reads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/api/agent/actions?")) {
        reads += 1;
        return Response.json(reads < 3 ? [] : [publishAction]);
      }
      return Response.json([], { status: 200 });
    });

    render(
      <ActionCenter
        workspaceId="w1"
        showDiagnostic={false}
        actionType="knowledge.publish"
        watchExecutionId="publish-run"
      />,
      { wrapper },
    );

    expect(await screen.findByText("正在等待待确认动作…")).toBeInTheDocument();
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    expect(reads).toBeGreaterThanOrEqual(3);
  });

  it("retries after waiting for a publication action times out", async () => {
    const publishAction: PendingAction = {
      ...action,
      id: "pub-retry",
      executionId: "publish-retry-run",
      actionType: "knowledge.publish",
      preview: { title: "重试后出现" },
      editableFields: [],
    };
    let available = false;
    vi.spyOn(globalThis, "setTimeout").mockImplementation(((callback: TimerHandler) => {
      queueMicrotask(() => {
        if (typeof callback === "function") callback();
      });
      return 0;
    }) as typeof setTimeout);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/api/agent/actions?")) {
        return Response.json(available ? [publishAction] : []);
      }
      return Response.json([], { status: 200 });
    });

    render(
      <ActionCenter
        workspaceId="w1"
        showDiagnostic={false}
        actionType="knowledge.publish"
        watchExecutionId="publish-retry-run"
      />,
      { wrapper },
    );

    await act(async () => {
      for (let index = 0; index < 60; index += 1) await Promise.resolve();
    });
    expect(screen.getByText(/待确认动作尚未出现/)).toBeInTheDocument();
    available = true;
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
    await act(async () => {
      for (let index = 0; index < 20; index += 1) await Promise.resolve();
    });
    expect(screen.getByText("重试后出现")).toBeInTheDocument();
  });
});
