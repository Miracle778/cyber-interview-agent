import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { AgentRunCenterPage } from "./AgentRunCenterPage";
import type { ExecutionSummary } from "./observabilityTypes";


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

const runningExecution: ExecutionSummary = {
  id: "run-running",
  sessionId: "session-running",
  workspaceId: "workspace-1",
  graphId: "question.curate",
  displayName: "题库整理",
  system: false,
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

const completedExecution: ExecutionSummary = {
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

const waitingExecution: ExecutionSummary = {
  ...runningExecution,
  id: "run-waiting",
  sessionId: "session-waiting",
  title: "补充项目背景",
  status: "waiting_for_input",
  capabilities: ["open_business", "resume"],
};

const failedExecution: ExecutionSummary = {
  ...runningExecution,
  id: "run-failed",
  sessionId: "session-failed",
  graphId: "review.discussion",
  title: "项目深入讨论",
  displayName: "深入讨论",
  status: "failed",
  traceHealth: "partial",
  capabilities: ["open_business", "retry", "manual_judge"],
  errorCode: "provider_unavailable",
};

const interruptedExecution: ExecutionSummary = {
  ...runningExecution,
  id: "run-interrupted",
  sessionId: "session-interrupted",
  title: "暂停的复盘分析",
  displayName: "面试复盘",
  status: "interrupted",
  capabilities: ["open_business", "resume"],
};

const cancelledExecution: ExecutionSummary = {
  ...runningExecution,
  id: "run-cancelled",
  sessionId: "session-cancelled",
  title: "取消的复盘分析",
  displayName: "面试复盘",
  status: "cancelled",
  capabilities: ["open_business"],
};

const recoveredCurationFailure: ExecutionSummary = {
  ...runningExecution,
  id: "run-curation-failed",
  sessionId: "session-curation-recovered",
  title: "题库整理任务",
  status: "failed",
  traceHealth: "complete",
  capabilities: ["open_business", "retry"],
  errorCode: "curation_work_item_failed",
  createdAt: "2026-07-29T00:29:00Z",
  startedAt: "2026-07-29T00:29:00Z",
  finishedAt: "2026-07-29T00:29:04Z",
};

const recoveredCurationCurrent: ExecutionSummary = {
  ...recoveredCurationFailure,
  id: "run-curation-recovered",
  status: "completed",
  capabilities: ["open_business"],
  errorCode: null,
  createdAt: "2026-07-29T00:51:00Z",
  startedAt: "2026-07-29T00:51:00Z",
  finishedAt: "2026-07-29T00:51:04Z",
};

function page(items = [runningExecution, completedExecution]) {
  const statusCounts = items.reduce<Record<string, number>>((counts, item) => ({
    ...counts,
    [item.status]: (counts[item.status] ?? 0) + 1,
  }), {});
  const agentCounts = items.reduce<Record<string, Record<string, number>>>(
    (counts, item) => ({
      ...counts,
      [item.displayName]: {
        ...(counts[item.displayName] ?? {}),
        [item.status]: (counts[item.displayName]?.[item.status] ?? 0) + 1,
      },
    }),
    {},
  );
  return {
    items,
    nextCursor: null,
    total: items.length,
    statusCounts,
    agentCounts,
  };
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

function taskList() {
  return screen.getByRole("region", { name: "任务列表" });
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

  it("renders the task-first layout with stable status tabs and friendly details", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    expect(screen.getByRole("heading", { level: 1, name: "Agent 运行中心" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "运行质量" })).toHaveAttribute(
      "href",
      "/agents/evaluations",
    );
    const tabs = await screen.findByRole("navigation", { name: "任务状态" });
    expect(within(tabs).getByRole("button", { name: "关注中 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(tabs).queryByRole("button", { name: "进行中 1" })).not.toBeInTheDocument();
    expect(within(tabs).getByRole("button", { name: "已完成 1" })).toBeInTheDocument();

    const row = within(taskList()).getByRole("button", {
      name: /MyBatis 拦截器资料整理/,
    });
    expect(row).toHaveTextContent("题库整理");
    expect(row).toHaveTextContent("任务正在处理中");
    expect(row).toHaveTextContent("运行中");
    expect(within(taskList()).getByRole("link", {
      name: "查看“MyBatis 拦截器资料整理”运行详情",
    })).toHaveAttribute("href", "/agents/executions/run-running");

    const preview = screen.getByRole("complementary", { name: "任务详情" });
    expect(preview).toHaveTextContent("接下来可以这样做");
    expect(preview).toHaveTextContent("12.8k");
  });

  it("preserves the URL status filter when the workspace finishes loading", async () => {
    mockPage();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const view = render(
      <MemoryRouter initialEntries={["/agents?status=completed"]}>
        <QueryClientProvider client={client}>
          <AgentRunCenterPage workspace={null} />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    view.rerender(
      <MemoryRouter initialEntries={["/agents?status=completed"]}>
        <QueryClientProvider client={client}>
          <AgentRunCenterPage workspace={workspace} />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    const tabs = await screen.findByRole("navigation", { name: "任务状态" });
    await waitFor(() => {
      expect(within(tabs).getByRole("button", { name: "已完成 1" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
  });

  it("keeps the action center as a compact filter without duplicating task rows", async () => {
    mockPage(page([
      runningExecution,
      waitingExecution,
      failedExecution,
      completedExecution,
    ]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    const actionCenter = await screen.findByRole("region", { name: "需要你处理" });
    await waitFor(() => {
      expect(screen.getByRole("button", {
        name: "查看需要你处理的 2 个任务",
      })).toHaveAttribute("aria-pressed", "false");
    });
    expect(within(screen.getByRole("navigation", { name: "任务状态" }))
      .getByRole("button", { name: "关注中 3" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(actionCenter).not.toHaveTextContent("补充项目背景");
    expect(actionCenter).not.toHaveTextContent("项目深入讨论");
    expect(within(taskList()).getByRole("button", {
      name: /补充项目背景/,
    })).toBeInTheDocument();
    expect(within(taskList()).getByRole("button", {
      name: /项目深入讨论/,
    })).toBeInTheDocument();
  });

  it("defaults to actionable tasks and lets the yellow summary restore that filter", async () => {
    mockPage(page([
      completedExecution,
      waitingExecution,
      failedExecution,
    ]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    const tabs = await screen.findByRole("navigation", { name: "任务状态" });

    await waitFor(() => {
      expect(within(tabs).getByRole("button", { name: "关注中 2" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(within(taskList()).queryByRole("button", {
      name: /简历 v3 画像建议/,
    })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("complementary", { name: "任务详情" })).toHaveTextContent(
        "补充项目背景",
      );
    });

    fireEvent.click(within(tabs).getByRole("button", { name: "全部 3" }));
    expect(within(taskList()).getByRole("button", {
      name: /简历 v3 画像建议/,
    })).toBeInTheDocument();

    const summary = screen.getByRole("button", {
      name: "查看需要你处理的 2 个任务",
    });
    expect(summary).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(summary);
    expect(summary).toHaveAttribute("aria-pressed", "true");
    expect(within(taskList()).queryByRole("button", {
      name: /简历 v3 画像建议/,
    })).not.toBeInTheDocument();
  });

  it("filters locally through stable task-status tabs without hiding other tabs", async () => {
    const fetchSpy = mockPage(page([
      runningExecution,
      waitingExecution,
      failedExecution,
      completedExecution,
    ]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    const tabs = await screen.findByRole("navigation", { name: "任务状态" });

    fireEvent.click(within(tabs).getByRole("button", { name: "关注中 3" }));
    expect(within(taskList()).getByRole("button", {
      name: /MyBatis 拦截器资料整理/,
    })).toBeInTheDocument();
    expect(within(taskList()).getByRole("button", {
      name: /补充项目背景/,
    })).toBeInTheDocument();
    expect(within(tabs).getByRole("button", { name: "全部 4" })).toBeInTheDocument();
    expect(within(tabs).getByRole("button", { name: "已完成 1" })).toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    fireEvent.click(within(tabs).getByRole("button", { name: "已完成 1" }));
    expect(within(taskList()).getByRole("button", {
      name: /简历 v3 画像建议/,
    })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("offers a quick filter for paused and cancelled tasks", async () => {
    mockPage(page([
      completedExecution,
      interruptedExecution,
      cancelledExecution,
    ]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    const tabs = await screen.findByRole("navigation", { name: "任务状态" });
    const stoppedTab = within(tabs).getByRole("button", {
      name: "已暂停/取消 2",
    });

    fireEvent.click(stoppedTab);

    expect(stoppedTab).toHaveAttribute("aria-pressed", "true");
    expect(within(taskList()).getByRole("button", {
      name: /暂停的复盘分析/,
    })).toBeInTheDocument();
    expect(within(taskList()).getByRole("button", {
      name: /取消的复盘分析/,
    })).toBeInTheDocument();
    expect(within(taskList()).queryByRole("button", {
      name: /简历 v3 画像建议/,
    })).not.toBeInTheDocument();
  });

  it("uses one responsive filter panel for Agent, detailed status, and system tasks", async () => {
    const fetchSpy = mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    await screen.findByRole("button", { name: "筛选" });

    const trigger = screen.getByRole("button", { name: "筛选" });
    fireEvent.click(trigger);
    const filters = screen.getByRole("region", { name: "运行筛选" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByLabelText("运行状态")).toHaveLength(1);
    expect(within(filters).getByRole("option", {
      name: "关注中（需处理或进行中）",
    })).toBeInTheDocument();
    expect(within(filters).getByRole("option", { name: "仅需要我处理" })).toBeInTheDocument();
    expect(within(filters).getByRole("option", { name: "仅进行中" })).toBeInTheDocument();
    expect(within(filters).getByRole("option", { name: "已停止" })).toBeInTheDocument();

    fireEvent.change(within(filters).getByLabelText("运行状态"), {
      target: { value: "" },
    });
    fireEvent.change(within(filters).getByLabelText("Agent"), {
      target: { value: "画像助手" },
    });
    expect(within(taskList()).getByRole("button", {
      name: /简历 v3 画像建议/,
    })).toBeInTheDocument();

    fireEvent.click(within(filters).getByRole("checkbox", {
      name: "包含系统 Agent",
    }));
    await waitFor(() => {
      expect(String(fetchSpy.mock.calls.at(-1)?.[0])).toContain(
        "includeSystemAgents=true",
      );
    });
  });

  it("searches tasks and provides a clear-filter recovery state", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    await screen.findByRole("searchbox", { name: "搜索运行" });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索运行" }), {
      target: { value: "不存在的任务" },
    });
    expect(screen.getByText("没有找到符合条件的任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(within(taskList()).getByRole("button", {
      name: /MyBatis 拦截器资料整理/,
    })).toBeInTheDocument();
  });

  it("keeps the preview closed until another task is selected", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    await screen.findByRole("complementary", { name: "任务详情" });
    fireEvent.click(screen.getByRole("button", { name: "关闭任务详情" }));
    expect(screen.queryByRole("complementary", { name: "任务详情" })).not.toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("navigation", { name: "任务状态" }))
      .getByRole("button", { name: "全部 2" }));
    fireEvent.click(within(taskList()).getByRole("button", {
      name: /简历 v3 画像建议/,
    }));
    expect(screen.getByRole("complementary", { name: "任务详情" })).toHaveTextContent(
      "简历 v3 画像建议",
    );
  });

  it("derives real navigation actions from capabilities and registry routes", async () => {
    mockPage();

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    await screen.findByRole("complementary", { name: "任务详情" });
    let preview = screen.getByRole("complementary", { name: "任务详情" });
    expect(within(preview).getByRole("link", { name: "查看任务页面" })).toHaveAttribute(
      "href",
      "/review?section=catalog&curationSessionId=session-running&returnTo=%2Fagents%3Fstatus%3Dfocused",
    );
    expect(within(preview).getByRole("link", { name: "查看运行详情" })).toHaveAttribute(
      "href",
      "/agents/executions/run-running",
    );
    expect(within(preview).queryByRole("link", { name: "检查运行质量" })).not.toBeInTheDocument();
    expect(
      within(screen.getByText("查看技术详情").closest("details")!)
        .queryByRole("link", { name: /运行详情/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("navigation", { name: "任务状态" }))
      .getByRole("button", { name: "全部 2" }));
    fireEvent.click(within(taskList()).getByRole("button", {
      name: /简历 v3 画像建议/,
    }));
    preview = screen.getByRole("complementary", { name: "任务详情" });
    expect(within(preview).getByRole("link", { name: "查看运行详情" })).toHaveAttribute(
      "href",
      "/agents/executions/run-completed",
    );
    expect(within(preview).getByRole("link", { name: "检查运行质量" })).toHaveAttribute(
      "href",
      "/agents/evaluations?executionId=run-completed",
    );
  });

  it("labels a generic Agent landing route honestly when no session deep link exists", async () => {
    mockPage(page([failedExecution]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    const preview = await screen.findByRole("complementary", { name: "任务详情" });
    await waitFor(() => {
      expect(within(preview).getByRole("link", { name: "打开业务页面" })).toHaveAttribute(
        "href",
        "/review?returnTo=%2Fagents%3Fstatus%3Dfocused",
      );
    });
    expect(within(preview).getByRole("link", { name: "查看失败详情" })).toHaveAttribute(
      "href",
      "/agents/executions/run-failed",
    );
    expect(within(preview).queryByRole("link", { name: "查看并处理" })).not.toBeInTheDocument();
  });

  it("shows one current task per session while keeping historical executions out of task counts", async () => {
    mockPage(page([
      recoveredCurationFailure,
      waitingExecution,
      recoveredCurationCurrent,
    ]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    const tabs = await screen.findByRole("navigation", { name: "任务状态" });
    await waitFor(() => {
      expect(within(tabs).getByRole("button", { name: "关注中 1" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByRole("button", {
      name: "查看需要你处理的 1 个任务",
    })).toBeInTheDocument();
    expect(within(taskList()).queryByRole("button", {
      name: /题库整理任务/,
    })).not.toBeInTheDocument();

    fireEvent.click(within(tabs).getByRole("button", { name: "全部 2" }));
    const currentRow = within(taskList()).getByRole("button", {
      name: /题库整理任务/,
    });
    fireEvent.click(currentRow);
    expect(currentRow).toHaveTextContent("已完成");
    expect(within(taskList()).getAllByRole("button", {
      name: /题库整理任务/,
    })).toHaveLength(1);
    expect(within(tabs).getByRole("button", { name: "已完成 1" }))
      .toBeInTheDocument();
    expect(within(tabs).getByRole("button", { name: "失败 0" }))
      .toBeInTheDocument();

    fireEvent.click(within(taskList()).getByRole("button", {
      name: "查看 2 次运行",
    }));
    const history = within(taskList()).getByRole("region", {
      name: "题库整理任务的运行记录",
    });
    expect(within(history).getByText("第 2 次")).toBeInTheDocument();
    expect(within(history).getByText("当前运行")).toBeInTheDocument();
    expect(within(history).getByText("第 1 次")).toBeInTheDocument();
    expect(within(history).getByText("历史失败·已恢复")).toBeInTheDocument();
    expect(within(history).getByRole("link", {
      name: "查看第 2 次运行详情",
    })).toHaveAttribute("href", "/agents/executions/run-curation-recovered");
    expect(within(history).getByRole("link", {
      name: "查看第 1 次运行详情",
    })).toHaveAttribute("href", "/agents/executions/run-curation-failed");

    const preview = screen.getByRole("complementary", { name: "任务详情" });
    expect(within(preview).getByRole("link", { name: "查看运行详情" })).toHaveAttribute(
      "href",
      "/agents/executions/run-curation-recovered",
    );
  });

  it("replaces synthetic trace filenames with a readable task name", async () => {
    mockPage(page([{
      ...completedExecution,
      title: "source_aabbcc.md",
    }]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });

    expect(await within(await screen.findByRole("region", { name: "任务列表" }))
      .findByRole("button", { name: /画像助手任务/ })).toBeInTheDocument();
    expect(screen.queryByText("source_aabbcc.md")).not.toBeInTheDocument();
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
    expect(await screen.findByText("当前还没有 Agent 任务")).toBeInTheDocument();
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

  it("shows default-visible system tasks while keeping internal system tasks hidden", async () => {
    mockPage(page([runningExecution]));

    render(<AgentRunCenterPage workspace={workspace} />, { wrapper });
    fireEvent.click(within(await screen.findByRole("navigation", { name: "任务状态" }))
      .getByRole("button", { name: "全部 1" }));
    const row = await within(await screen.findByRole("region", { name: "任务列表" }))
      .findByRole("button", { name: /MyBatis 拦截器资料整理/ });
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

    await act(async () => {
      FakeEventSource.instances[0].emit("execution.summary.changed", {
        eventId: "10",
        type: "execution.summary.changed",
        execution: {
          ...completedExecution,
          id: "run-system-live",
          sessionId: "session-system-live",
          graphId: "profile.ingest",
          displayName: "简历画像整理",
          title: "系统画像任务",
          system: true,
          runCenterDefaultVisible: true,
        },
      });
    });
    expect(screen.getByRole("button", { name: /系统画像任务/ })).toBeInTheDocument();

    await act(async () => {
      FakeEventSource.instances[0].emit("execution.summary.changed", {
        eventId: "11",
        type: "execution.summary.changed",
        execution: {
          ...completedExecution,
          id: "run-internal-system-live",
          sessionId: "session-internal-system-live",
          graphId: "diagnostic.echo",
          displayName: "系统诊断",
          title: "内部诊断任务",
          system: true,
          runCenterDefaultVisible: false,
        },
      });
    });
    expect(screen.queryByRole("button", { name: /内部诊断任务/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "包含系统 Agent" }));
    expect(await within(taskList()).findByRole("button", {
      name: /系统画像任务/,
    })).toBeInTheDocument();
    expect(await within(taskList()).findByRole("button", {
      name: /内部诊断任务/,
    })).toBeInTheDocument();
  });

  it("does not query without a selected workspace", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<AgentRunCenterPage workspace={null} />, { wrapper });

    expect(screen.getByText("请先选择工作区后查看 Agent 运行。")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
