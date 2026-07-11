import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuntimeDiagnostics } from "./RuntimeDiagnostics";
import type { AgentSessionDetail } from "../agent/agentTypes";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent<string>) => void>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener);
  }

  close() {}

  emit(event: object) {
    const type = (event as { type: string }).type;
    this.listeners.get(type)?.({ data: JSON.stringify(event) } as MessageEvent<string>);
  }
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {children}
    </QueryClientProvider>
  );
}

describe("RuntimeDiagnostics", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    FakeEventSource.instances = [];
  });

  it("creates a diagnostic session, runs it, and presents deduplicated events", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    let detail: AgentSessionDetail = {
      id: "s1",
      workspaceId: "w1",
      graphId: "test.echo",
      graphVersion: 1,
      title: "Agent Runtime 自检",
      status: "active",
      createdAt: "now",
      updatedAt: "now",
      lastRunId: "r1",
      messages: [],
      latestRun: { id: "r1", sessionId: "s1", status: "running", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null },
      pendingAction: null,
    };
    let startCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("workspaceId=w1")) return Response.json([]);
      if (url === "/api/agent/sessions" && method === "POST") return Response.json({ ...detail, lastRunId: null }, { status: 201 });
      if (url === "/api/agent/sessions/s1/runs") {
        startCount += 1;
        return Response.json(
          startCount === 1
            ? detail.latestRun
            : { ...detail.latestRun, id: "r2", status: "queued" },
          { status: 202 },
        );
      }
      if (url === "/api/agent/sessions/s1") return Response.json(detail);
      return Response.json({ code: "unexpected", message: url }, { status: 500 });
    });

    render(<RuntimeDiagnostics workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("Runtime 已就绪，可以运行自检")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行自检" }));

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    act(() => source.onopen?.(new Event("open")));
    const completed = { id: 3, type: "run.completed", sessionId: "s1", runId: "r1", timestamp: "now", payload: {} };
    act(() => {
      source.emit({ id: 1, type: "run.started", sessionId: "s1", runId: "r1", timestamp: "now", payload: {} });
      source.emit({ id: 2, type: "message.completed", sessionId: "s1", runId: "r1", timestamp: "now", payload: { messageId: "m1", content: "Echo: runtime-check" } });
      source.emit(completed);
      source.emit(completed);
    });
    detail = {
      ...detail,
      latestRun: {
        ...(detail.latestRun as NonNullable<AgentSessionDetail["latestRun"]>),
        status: "completed",
        finishedAt: "now",
      },
    };

    expect(await screen.findByText("自检完成")).toBeInTheDocument();
    expect(screen.getAllByText("运行完成")).toHaveLength(1);
    expect(screen.getByText("SSE 已连接")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行自检" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "运行自检" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "运行自检" })).toBeDisabled(),
    );
  });

  it("restores the newest diagnostic session and shows recovery advice on failure", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const session = { id: "s1", workspaceId: "w1", graphId: "test.echo", graphVersion: 1, title: "Agent Runtime 自检", status: "active", createdAt: "now", updatedAt: "now", lastRunId: "r1" };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("workspaceId=w1")) return Response.json([session]);
      if (url === "/api/agent/sessions/s1") return Response.json({ ...session, messages: [], latestRun: { id: "r1", sessionId: "s1", status: "failed", resumeCount: 0, errorCode: "runtime_error", errorMessage: "failed", createdAt: "now", startedAt: "now", finishedAt: "now" }, pendingAction: null });
      return Response.json({}, { status: 500 });
    });

    render(<RuntimeDiagnostics workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("自检失败")).toBeInTheDocument();
    expect(screen.getByText("请检查后端日志与模型配置后重试")).toBeInTheDocument();
    expect(FakeEventSource.instances[0].url).toBe("/api/agent/sessions/s1/events");
  });
});
