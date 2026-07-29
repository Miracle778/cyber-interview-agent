import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { AgentRunCenterPage } from "./AgentRunCenterPage";


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

  emit(type: string, payload: unknown) {
    this.listeners.get(type)?.({
      data: JSON.stringify(payload),
    } as MessageEvent<string>);
  }

  close = vi.fn();
}

const workspace: WorkspaceConfig = {
  id: "workspace-1",
  displayName: "面试准备",
  workspacePath: "/tmp/interview",
  vaultPath: "/tmp/interview/vault",
};

const runningExecution = {
  id: "run-running",
  sessionId: "session-running",
  workspaceId: "workspace-1",
  graphId: "question.curate",
  displayName: "题库整理",
  title: "MyBatis 拦截器资料整理",
  status: "running",
  traceHealth: "complete",
  capabilities: ["open_business", "cancel"],
  route: "/review",
  systemOperationCount: 2,
  modelCallCount: 1,
  totalTokens: 12800,
  contextCurrentTokens: 18400,
  contextThresholdTokens: 90000,
  latencyMs: 96000,
  retryCount: 0,
  createdAt: "2026-07-29T06:26:00Z",
  startedAt: "2026-07-29T06:26:00Z",
  finishedAt: null,
  errorCode: null,
};

const completedExecution = {
  ...runningExecution,
  id: "run-completed",
  sessionId: "session-completed",
  graphId: "profile.manage",
  displayName: "画像助手",
  title: "简历 v3 画像建议",
  status: "completed",
  traceHealth: "missing",
  capabilities: ["manual_judge"],
  route: "",
  totalTokens: 8100,
  latencyMs: 42000,
  createdAt: "2026-07-29T06:24:00Z",
  startedAt: "2026-07-29T06:24:00Z",
  finishedAt: "2026-07-29T06:24:42Z",
};

function page(items = [runningExecution, completedExecution]) {
  return { items, nextCursor: null, total: items.length };
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })}
      >
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  );
}

function mockPage(payload: unknown = page()) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => Response.json(payload),
  );
}

describe("AgentRunCenterPage", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders real execution summaries with Beijing time and compact token values", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    expect(screen.getByRole("heading", { level: 1, name: "Agent 运行中心" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "运行汇总" })).toHaveTextContent("运行中1");
    expect(screen.getByRole("region", { name: "运行汇总" })).toHaveTextContent("今日完成1");
    const row = screen.getByRole("button", { name: /MyBatis 拦截器资料整理/ });
    expect(row).toHaveTextContent("题库整理");
    expect(row).toHaveTextContent("12.8k");
    expect(row).toHaveTextContent("14:26");
    expect(row).toHaveTextContent("运行中");
  });

  it("filters by status, search text, and explicit system-agent inclusion", async () => {
    const fetchSpy = mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    await screen.findByRole("button", { name: /MyBatis 拦截器资料整理/ });

    fireEvent.change(screen.getByLabelText("运行状态"), {
      target: { value: "failed" },
    });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索运行" }), {
      target: { value: "MyBatis" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "包含系统 Agent" }));

    await waitFor(() => {
      const latestUrl = String(fetchSpy.mock.calls.at(-1)?.[0]);
      expect(latestUrl).toContain("status=failed");
      expect(latestUrl).toContain("search=MyBatis");
      expect(latestUrl).toContain("includeSystemAgents=true");
    });
  });

  it("derives navigation actions from capabilities and registry routes", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    const running = await screen.findByRole("button", {
      name: /MyBatis 拦截器资料整理/,
    });
    fireEvent.click(running);

    const preview = screen.getByRole("complementary", { name: "本次运行" });
    expect(within(preview).getByRole("link", { name: "查看运行详情" })).toHaveAttribute(
      "href",
      "/agents/executions/run-running",
    );
    expect(within(preview).getByRole("link", { name: "打开业务页面" })).toHaveAttribute("href", "/review");

    fireEvent.click(screen.getByRole("button", { name: /简历 v3 画像建议/ }));
    expect(within(preview).queryByRole("link", { name: "打开业务页面" })).not.toBeInTheDocument();
  });

  it("shows loading, empty, API error, and malformed-payload states without fake zeroes", async () => {
    let resolveRequest: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    const first = render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    expect(screen.getByRole("status")).toHaveTextContent("正在读取 Agent 运行");
    resolveRequest?.(Response.json(page([])));
    expect(await screen.findByText("当前还没有 Agent 运行记录")).toBeInTheDocument();
    first.unmount();

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const second = render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取 Agent 运行");
    second.unmount();

    vi.restoreAllMocks();
    mockPage({ items: [{ id: "broken" }], total: 1, nextCursor: null });
    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    expect(await screen.findByRole("alert")).toHaveTextContent("运行数据格式不完整");
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it("applies live execution summary changes without reloading the page", async () => {
    mockPage(page([runningExecution]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    const row = await screen.findByRole("button", {
      name: /MyBatis 拦截器资料整理/,
    });
    expect(row).toHaveTextContent("运行中");
    expect(FakeEventSource.instances[0].url).toBe(
      "/api/agent-observability/events?workspaceId=workspace-1",
    );

    FakeEventSource.instances[0].emit("execution.summary.changed", {
      eventId: "9",
      type: "execution.summary.changed",
      execution: {
        ...runningExecution,
        status: "completed",
        capabilities: ["manual_judge"],
        finishedAt: "2026-07-29T06:27:36Z",
      },
    });

    await waitFor(() => expect(row).toHaveTextContent("已完成"));
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("does not query without a selected workspace", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<AgentRunCenterPage workspace={null} />, { wrapper });

    expect(screen.getByText("请先选择工作区后查看 Agent 运行。")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
