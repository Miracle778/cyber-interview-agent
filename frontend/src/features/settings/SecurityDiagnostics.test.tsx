import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentSessionDetail } from "../agent/agentTypes";
import { SecurityDiagnostics } from "./SecurityDiagnostics";

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

function event(id: number, type: string, payload: Record<string, unknown>) {
  return { id, type, sessionId: "s1", runId: "r1", timestamp: "now", payload };
}

describe("SecurityDiagnostics", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    FakeEventSource.instances = [];
  });

  it("runs all four checks and renders only normalized security results", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    let detail: AgentSessionDetail = {
      id: "s1",
      workspaceId: "w1",
      graphId: "test.tool-security",
      graphVersion: 1,
      title: "工具安全自检",
      status: "active",
      createdAt: "now",
      updatedAt: "now",
      lastRunId: "r1",
      messages: [],
      latestRun: { id: "r1", sessionId: "s1", status: "running", resumeCount: 0, errorCode: null, errorMessage: null, createdAt: "now", startedAt: "now", finishedAt: null },
      pendingAction: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("workspaceId=w1")) return Response.json([]);
      if (url === "/api/agent/sessions" && method === "POST") {
        return Response.json({ ...detail, lastRunId: null }, { status: 201 });
      }
      if (url === "/api/agent/sessions/s1/runs") {
        return Response.json(detail.latestRun, { status: 202 });
      }
      if (url === "/api/agent/sessions/s1") return Response.json(detail);
      return Response.json({ code: "unexpected", message: url }, { status: 500 });
    });

    render(<SecurityDiagnostics workspaceId="w1" />, { wrapper });
    expect(await screen.findByText("工具安全策略已就绪")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行安全自检" }));

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    act(() => source.onopen?.(new Event("open")));
    act(() => {
      source.emit(event(1, "tool.completed", { toolName: "diagnostic_read", resourcePath: "probe.txt" }));
      source.emit(event(2, "tool.failed", { toolName: "shell", code: "tool_not_allowed" }));
      source.emit(event(3, "tool.failed", { toolName: "read_active_knowledge", code: "tool_scope_denied" }));
      source.emit(event(4, "tool.failed", { toolName: "diagnostic_read", code: "workspace_path_denied" }));
      source.emit(event(4, "tool.failed", { toolName: "diagnostic_read", code: "workspace_path_denied", content: "must-not-render" }));
      source.emit(event(5, "run.completed", {}));
    });
    detail = {
      ...detail,
      latestRun: { ...detail.latestRun!, status: "completed", finishedAt: "now" },
    };

    expect(await screen.findByText("工具安全自检通过")).toBeInTheDocument();
    expect(screen.getByText("授权读取通过")).toBeInTheDocument();
    expect(screen.getByText("未注册工具已拒绝")).toBeInTheDocument();
    expect(screen.getByText("未授权 Scope 已拒绝")).toBeInTheDocument();
    expect(screen.getByText("路径越界已拒绝")).toBeInTheDocument();
    expect(screen.getByText("SSE 已连接")).toBeInTheDocument();
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行安全自检" })).toBeEnabled();
  });

  it("restores a failed diagnostic and presents actionable advice", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const session = { id: "s1", workspaceId: "w1", graphId: "test.tool-security", graphVersion: 1, title: "工具安全自检", status: "active", createdAt: "now", updatedAt: "now", lastRunId: "r1" };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("workspaceId=w1")) return Response.json([session]);
      if (url === "/api/agent/sessions/s1") return Response.json({ ...session, messages: [], latestRun: { id: "r1", sessionId: "s1", status: "failed", resumeCount: 0, errorCode: "runtime_error", errorMessage: "failed", createdAt: "now", startedAt: "now", finishedAt: "now" }, pendingAction: null });
      return Response.json({}, { status: 500 });
    });

    render(<SecurityDiagnostics workspaceId="w1" />, { wrapper });

    expect(await screen.findByText("工具安全自检失败")).toBeInTheDocument();
    expect(screen.getByText("请检查后端工具审计记录后重试")).toBeInTheDocument();
    expect(FakeEventSource.instances[0].url).toBe("/api/agent/sessions/s1/events");
  });
});
