import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ExecutionTracePage } from "./ExecutionTracePage";


const workspace: WorkspaceConfig = {
  id: "workspace-1",
  displayName: "面试准备",
  workspacePath: "/tmp/interview",
  vaultPath: "/tmp/interview/vault",
};

const execution = {
  id: "run-1",
  sessionId: "session-1",
  workspaceId: "workspace-1",
  graphId: "question.curate",
  displayName: "题库整理",
  title: "MyBatis 拦截器资料整理",
  status: "completed",
  traceHealth: "complete",
  capabilities: ["open_business"],
  route: "/knowledge",
  systemOperationCount: 3,
  modelCallCount: 1,
  totalTokens: 12800,
  contextCurrentTokens: 18400,
  contextThresholdTokens: 90000,
  latencyMs: 18400,
  retryCount: 0,
  createdAt: "2026-07-29T06:26:00Z",
  startedAt: "2026-07-29T06:26:00Z",
  finishedAt: "2026-07-29T06:26:18.400Z",
  errorCode: null,
};

const operations = [
  {
    id: "execution:run-1",
    runId: "run-1",
    parentOperationId: null,
    kind: "execution",
    name: "题库整理运行",
    agentRole: null,
    status: "completed",
    startedAt: "2026-07-29T06:26:00Z",
    finishedAt: "2026-07-29T06:26:18.400Z",
    latencyMs: 18400,
    retryCount: 0,
    errorCode: null,
    eventCount: 3,
  },
  {
    id: "agent-1",
    runId: "run-1",
    parentOperationId: "execution:run-1",
    kind: "agent",
    name: "发现候选题",
    agentRole: "question_generation",
    status: "completed",
    startedAt: "2026-07-29T06:26:01Z",
    finishedAt: "2026-07-29T06:26:17Z",
    latencyMs: 16000,
    retryCount: 0,
    errorCode: null,
    eventCount: 2,
  },
  {
    id: "model-1",
    runId: "run-1",
    parentOperationId: "agent-1",
    kind: "model",
    name: "识别候选题",
    agentRole: "question_generation",
    status: "completed",
    startedAt: "2026-07-29T06:26:02Z",
    finishedAt: "2026-07-29T06:26:14Z",
    latencyMs: 12000,
    retryCount: 0,
    errorCode: null,
    eventCount: 1,
  },
];

function mockTrace(
  summary: unknown = execution,
  operationItems: unknown = operations,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/operations?")) {
      return Response.json({ items: operationItems });
    }
    if (url.includes("/api/agent-observability/executions/run-1?")) {
      return Response.json(summary);
    }
    throw new Error(`unexpected request: ${url}`);
  });
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: { queries: { retry: false } },
      })}
    >
      {children}
    </QueryClientProvider>
  );
}

function renderTrace(from = "/agents?status=failed&search=MyBatis") {
  return render(
    <MemoryRouter
      initialEntries={[{
        pathname: "/agents/executions/run-1",
        state: { from },
      }]}
    >
      <Providers>
        <Routes>
          <Route
            path="/agents/executions/:runId"
            element={<ExecutionTracePage workspace={workspace} />}
          />
        </Routes>
      </Providers>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ExecutionTracePage", () => {
  it("renders a hierarchical operation tree and only safe operation metadata", async () => {
    const fetchSpy = mockTrace();

    renderTrace();

    expect(await screen.findByRole("heading", {
      level: 1,
      name: "MyBatis 拦截器资料整理",
    })).toBeInTheDocument();
    const tree = screen.getByRole("tree", { name: "执行过程" });
    expect(within(tree).getByRole("treeitem", { name: /题库整理运行/ })).toHaveAttribute("aria-level", "1");
    expect(within(tree).getByRole("treeitem", { name: /发现候选题/ })).toHaveAttribute("aria-level", "2");
    expect(within(tree).getByRole("treeitem", { name: /识别候选题/ })).toHaveAttribute("aria-level", "3");

    fireEvent.click(within(tree).getByRole("treeitem", { name: /识别候选题/ }));
    const detail = screen.getByRole("region", { name: "Operation 详情" });
    expect(detail).toHaveTextContent("模型调用");
    expect(detail).toHaveTextContent("12 秒");
    expect(detail).toHaveTextContent("事件数1");
    expect(detail).toHaveTextContent("完整内容需开启高级诊断");
    expect(detail).not.toHaveTextContent("system prompt");
    expect(detail).not.toHaveTextContent("tool arguments");
    expect(detail).not.toHaveTextContent("provider payload");

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    for (const [request] of fetchSpy.mock.calls) {
      expect(String(request)).not.toMatch(/body|content|prompt|payload|events/);
    }
  });

  it("keeps v2 linear operations readable and explains the compatibility fallback", async () => {
    mockTrace(execution, operations.slice(1).map((operation) => ({
      ...operation,
      parentOperationId: null,
    })));

    renderTrace();

    expect(await screen.findByText("历史诊断信息不完整，已按时间顺序展示。")).toBeInTheDocument();
    const tree = screen.getByRole("tree", { name: "执行过程" });
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(2);
    expect(within(tree).getByRole("treeitem", { name: /发现候选题/ })).toHaveAttribute("aria-level", "1");
    expect(within(tree).getByRole("treeitem", { name: /识别候选题/ })).toHaveAttribute("aria-level", "1");
  });

  it("degrades missing and partial traces without turning them into page errors", async () => {
    mockTrace({ ...execution, traceHealth: "missing" }, []);
    const first = renderTrace();

    expect(await screen.findByText("本次运行缺少高级诊断记录")).toBeInTheDocument();
    expect(screen.getByText("没有可用的执行过程记录")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    first.unmount();

    vi.restoreAllMocks();
    mockTrace({ ...execution, traceHealth: "partial" }, operations.slice(0, 2));
    renderTrace();
    expect(await screen.findByText("本次运行的诊断记录不完整")).toBeInTheDocument();
    expect(screen.getByRole("tree", { name: "执行过程" })).toBeInTheDocument();
  });

  it("supports a mobile process/detail switch without losing selection", async () => {
    mockTrace();
    renderTrace();
    await screen.findByRole("tree", { name: "执行过程" });

    const switcher = screen.getByRole("navigation", { name: "详情视图" });
    fireEvent.click(within(switcher).getByRole("button", { name: "详情" }));
    expect(screen.getByRole("region", { name: "Operation 详情" })).toHaveAttribute("data-mobile-active", "true");
    fireEvent.click(within(switcher).getByRole("button", { name: "执行过程" }));
    expect(screen.getByRole("region", { name: "执行过程面板" })).toHaveAttribute("data-mobile-active", "true");
  });

  it("preserves the run-center filter URL when navigating back from a deep link", async () => {
    mockTrace();
    renderTrace();

    const back = await screen.findByRole("link", { name: "返回运行中心" });
    expect(back).toHaveAttribute("href", "/agents?status=failed&search=MyBatis");
  });

  it("does not query without a selected workspace", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <MemoryRouter initialEntries={["/agents/executions/run-1"]}>
        <Providers>
          <ExecutionTracePage workspace={null} />
        </Providers>
      </MemoryRouter>,
    );

    expect(screen.getByText("请先选择工作区。")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
