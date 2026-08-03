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
  system: false,
  title: "MyBatis 拦截器资料整理",
  status: "completed",
  traceHealth: "complete",
  capabilities: ["open_business"],
  route: "/review",
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

const previousExecution = {
  ...execution,
  id: "run-previous",
  sessionId: "session-previous",
  title: "上一轮题库整理",
  status: "failed",
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
  eventItems: unknown = [],
  advancedEnabled = false,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/settings/providers")) {
      return Response.json([]);
    }
    if (url.includes("/api/settings/agent-diagnostics")) {
      return Response.json({
        advancedEnabled,
        updatedAt: "2026-07-29T06:20:00Z",
      });
    }
    if (url.includes("/events/") && url.includes("/content?")) {
      return Response.json({
        eventId: "event-1",
        eventType: "model.request",
        content: "{\"messages\":[\"private prompt\"]}",
        contentEncoding: "utf-8-json",
        offset: 0,
        nextOffset: null,
        complete: true,
        sha256: "abc",
        redactionsApplied: true,
      });
    }
    if (url.includes("/events?")) {
      return Response.json({ items: eventItems });
    }
    if (url.includes("/operations?")) {
      return Response.json({ items: operationItems });
    }
    if (url.includes("/api/agent-observability/executions?")) {
      return Response.json({
        items: [execution, previousExecution],
        nextCursor: null,
        total: 2,
      });
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

function renderTrace(from = "/agents?status=failed&search=MyBatis", search = "") {
  return render(
    <MemoryRouter
      initialEntries={[{
        pathname: "/agents/executions/run-1",
        search,
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
    const detail = screen.getByRole("region", { name: "步骤详情" });
    expect(detail).toHaveTextContent("模型调用");
    expect(detail).toHaveTextContent("12 秒");
    expect(detail).toHaveTextContent("事件数1");
    expect(detail).toHaveTextContent("完整内容需开启高级诊断");
    expect(detail).not.toHaveTextContent("system prompt");
    expect(detail).not.toHaveTextContent("tool arguments");
    expect(detail).not.toHaveTextContent("provider payload");

    expect(screen.queryByRole("navigation", { name: "运行索引" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看业务结果" })).toHaveAttribute(
      "href",
      "/review?section=catalog&curationSessionId=session-1&returnTo=%2Fagents%3Fstatus%3Dfailed%26search%3DMyBatis",
    );
    expect(screen.getByRole("region", { name: "执行过程面板" })).toHaveClass(
      "task-workspace__pane",
    );

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(4));
    for (const [request] of fetchSpy.mock.calls) {
      expect(String(request)).not.toMatch(/body|content|prompt|payload/);
    }
  });

  it("selects a safe event index before lazily loading its private body", async () => {
    const fetchSpy = mockTrace(execution, operations, [{
      eventId: "event-1",
      operationId: "model-1",
      eventType: "model.request",
      observedAt: "2026-07-29T06:26:02Z",
      byteLength: 44,
      sequence: 1,
    }], true);
    renderTrace();

    const eventItem = await screen.findByRole("treeitem", { name: /模型请求/ });
    expect(fetchSpy.mock.calls.some(([request]) =>
      String(request).includes("/content?"))).toBe(false);

    fireEvent.click(eventItem);
    expect(await screen.findByLabelText("可读 JSON")).toBeInTheDocument();
    expect(fetchSpy.mock.calls.some(([request]) =>
      String(request).includes("/content?"))).toBe(true);
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

  it("places detached operation roots between execution boundary events by sequence", async () => {
    const timelineOperations = [
      {
        ...operations[0],
        id: "runtime-wrapper",
        name: "execution_runtime",
      },
      {
        ...operations[1],
        id: "execution:run-1",
        parentOperationId: null,
        kind: "execution",
        name: "ab035da4-5269-41b4-a164-72f22dd0470a",
      },
      {
        ...operations[2],
        id: "model-child",
        parentOperationId: "execution:run-1",
      },
    ];
    mockTrace(execution, timelineOperations, [
      {
        eventId: "event-completed",
        operationId: "runtime-wrapper",
        eventType: "execution.completed",
        observedAt: "2026-07-29T06:26:18Z",
        byteLength: 541,
        sequence: 10,
      },
      {
        eventId: "event-response",
        operationId: "model-child",
        eventType: "model.response",
        observedAt: "2026-07-29T06:26:14Z",
        byteLength: 1499,
        sequence: 9,
      },
      {
        eventId: "event-started",
        operationId: "runtime-wrapper",
        eventType: "execution.started",
        observedAt: "2026-07-29T06:26:00Z",
        byteLength: 536,
        sequence: 1,
      },
      {
        eventId: "event-request",
        operationId: "model-child",
        eventType: "model.request",
        observedAt: "2026-07-29T06:26:02Z",
        byteLength: 1753,
        sequence: 4,
      },
    ]);

    renderTrace();

    const treeItems = await screen.findAllByRole("treeitem");
    const labels = treeItems.map((item) => item.textContent ?? "");
    expect(labels.findIndex((label) => label.includes("任务开始"))).toBeLessThan(
      labels.findIndex((label) => label.includes("本次运行")),
    );
    expect(labels.findIndex((label) => label.includes("模型请求"))).toBeLessThan(
      labels.findIndex((label) => label.includes("模型响应")),
    );
    expect(labels.findIndex((label) => label.includes("模型响应"))).toBeLessThan(
      labels.findIndex((label) => label.includes("任务完成")),
    );
    expect(screen.getByRole("treeitem", { name: /本次运行/ })).toHaveAttribute(
      "aria-level",
      "2",
    );
  });

  it("groups each review answer evaluation and hides meaningless resume markers", async () => {
    const reviewExecution = {
      ...execution,
      graphId: "review.round",
      displayName: "复习助手",
      status: "waiting_for_input",
      finishedAt: null,
    };
    const reviewOperations = [
      {
        ...operations[0],
        status: "running",
        finishedAt: null,
      },
      {
        ...operations[1],
        id: "evaluation-2",
        name: "review_round_evaluator:2",
        agentRole: "answer_evaluation",
        status: "completed",
      },
      {
        ...operations[2],
        id: "model-2",
        parentOperationId: "evaluation-2",
        name: "review_round_evaluator:2",
        agentRole: "answer_evaluation",
      },
      {
        ...operations[1],
        id: "evaluation-3",
        name: "review_round_evaluator:3",
        agentRole: "answer_evaluation",
        status: "completed",
      },
      {
        ...operations[2],
        id: "model-3",
        parentOperationId: "evaluation-3",
        name: "review_round_evaluator:3",
        agentRole: "answer_evaluation",
      },
    ];
    mockTrace(reviewExecution, reviewOperations, [
      { eventId: "start-1", operationId: "execution:run-1", eventType: "execution.started", observedAt: "2026-07-29T06:26:00Z", byteLength: 536, sequence: 1 },
      { eventId: "resume-2", operationId: "execution:run-1", eventType: "execution.started", observedAt: "2026-07-29T06:26:01Z", byteLength: 536, sequence: 2 },
      { eventId: "request-2", operationId: "model-2", eventType: "model.request", observedAt: "2026-07-29T06:26:02Z", byteLength: 800, sequence: 3 },
      { eventId: "response-2", operationId: "model-2", eventType: "model.response", observedAt: "2026-07-29T06:26:03Z", byteLength: 900, sequence: 4 },
      { eventId: "resume-3", operationId: "execution:run-1", eventType: "execution.started", observedAt: "2026-07-29T06:26:04Z", byteLength: 536, sequence: 5 },
      { eventId: "request-3", operationId: "model-3", eventType: "model.request", observedAt: "2026-07-29T06:26:05Z", byteLength: 800, sequence: 6 },
      { eventId: "response-3", operationId: "model-3", eventType: "model.response", observedAt: "2026-07-29T06:26:06Z", byteLength: 900, sequence: 7 },
    ]);

    renderTrace();

    const tree = await screen.findByRole("tree", { name: "执行过程" });
    expect(within(tree).getAllByRole("treeitem", { name: /任务开始/ })).toHaveLength(1);
    expect(within(tree).getByRole("treeitem", { name: /第 2 题 · 回答评价/ })).toBeInTheDocument();
    expect(within(tree).getByRole("treeitem", { name: /第 3 题 · 回答评价/ })).toBeInTheDocument();
    expect(within(tree).getAllByRole("treeitem", { name: /模型调用/ })).toHaveLength(2);
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
    expect(screen.getByRole("region", { name: "步骤详情" })).toHaveAttribute("data-mobile-active", "true");
    fireEvent.click(within(switcher).getByRole("button", { name: "执行过程" }));
    expect(screen.getByRole("region", { name: "执行过程面板" })).toHaveAttribute("data-mobile-active", "true");
  });

  it("preserves the run-center filter URL when navigating back from a deep link", async () => {
    mockTrace();
    renderTrace();

    const back = await screen.findByRole("link", { name: "返回运行中心" });
    expect(back).toHaveAttribute("href", "/agents?status=failed&search=MyBatis");
  });

  it("returns to the selected retrospective question when opened from a report", async () => {
    mockTrace();
    const returnTo = "/retrospectives?retrospectiveId=retro-1&questionId=q-2";
    renderTrace("/agents", `?returnTo=${encodeURIComponent(returnTo)}`);

    const back = await screen.findByRole("link", { name: "返回面试复盘" });
    expect(back).toHaveAttribute("href", returnTo);
  });

  it("leads with actionable failure guidance and reconciles unfinished step labels", async () => {
    const failedExecution = {
      ...execution,
      title: "source_d8355c0e7115445b8b92eca88762b9f6.md",
      status: "failed",
      errorCode: "curation_work_item_failed",
      finishedAt: "2026-07-29T06:26:04Z",
      latencyMs: 4000,
    };
    const failedOperations = [
      {
        ...operations[0],
        name: "execution_runtime",
        status: "failed",
        finishedAt: "2026-07-29T06:26:04Z",
        latencyMs: 4000,
        errorCode: "curation_work_item_failed",
      },
      {
        ...operations[1],
        name: "ab035da4-5269-41b4-a164-72f22dd0470a",
        status: "running",
        finishedAt: null,
        latencyMs: null,
      },
    ];
    mockTrace(failedExecution, failedOperations, [{
      eventId: "event-failed",
      operationId: "execution:run-1",
      eventType: "execution.failed",
      observedAt: "2026-07-29T06:26:04Z",
      byteLength: 623,
      sequence: 4,
    }], true);

    renderTrace();

    expect(await screen.findByRole("heading", {
      level: 1,
      name: "题库整理任务",
    })).toBeInTheDocument();
    const guidance = screen.getByRole("region", { name: "失败处理建议" });
    expect(guidance).toHaveTextContent("这次任务没有完成");
    expect(guidance).toHaveTextContent("发生了什么");
    expect(guidance).toHaveTextContent("影响范围");
    expect(guidance).toHaveTextContent("建议处理");
    expect(screen.getByRole("link", { name: "返回任务处理" })).toHaveAttribute(
      "href",
      "/review?section=catalog&curationSessionId=session-1&returnTo=%2Fagents%3Fstatus%3Dfailed%26search%3DMyBatis",
    );

    const tree = screen.getByRole("tree", { name: "执行过程" });
    expect(within(tree).getByRole("treeitem", { name: /运行任务/ })).toBeInTheDocument();
    expect(within(tree).getByRole("treeitem", { name: /Agent 处理 未记录结束/ })).toBeInTheDocument();
    const failedEvent = within(tree).getByRole("treeitem", { name: /任务失败/ });
    expect(failedEvent).toHaveAttribute("data-tone", "danger");
    expect(failedEvent).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("heading", { name: "任务失败" })).toBeInTheDocument();
    expect(screen.getByText("这一步没有完成")).toBeInTheDocument();
  });

  it("marks an earlier model failure as recovered after execution resumes", async () => {
    const resumedExecution = {
      ...execution,
      graphId: "review.round",
      displayName: "复习助手",
      status: "running",
      finishedAt: null,
    };
    const resumedOperations = [
      {
        ...operations[0],
        name: "execution_runtime",
        status: "running",
        finishedAt: null,
      },
      {
        ...operations[1],
        name: "review_round_evaluator",
        status: "failed",
        finishedAt: "2026-07-29T06:26:14Z",
      },
      {
        ...operations[2],
        name: "review_round_evaluator",
        status: "failed",
        finishedAt: "2026-07-29T06:26:14Z",
      },
    ];
    const resumedEvents = [
      {
        eventId: "event-model-error",
        operationId: "model-1",
        eventType: "model.error",
        observedAt: "2026-07-29T06:26:14Z",
        byteLength: 616,
        sequence: 4,
      },
      {
        eventId: "event-resumed",
        operationId: "execution:run-1",
        eventType: "execution.started",
        observedAt: "2026-07-29T06:26:15Z",
        byteLength: 536,
        sequence: 5,
      },
    ];
    mockTrace(resumedExecution, resumedOperations, resumedEvents);

    renderTrace();

    const tree = await screen.findByRole("tree", { name: "执行过程" });
    const recoveredEvent = within(tree).getByRole("treeitem", {
      name: /模型处理异常 · 已恢复/,
    });
    expect(recoveredEvent).toHaveAttribute("data-tone", "recovered");
    expect(within(tree).getByRole("treeitem", {
      name: /回答评价 历史异常 · 已恢复/,
    })).toBeInTheDocument();
    expect(within(tree).getByRole("treeitem", {
      name: /模型调用 历史异常 · 已恢复/,
    })).toBeInTheDocument();
    expect(within(tree).getByRole("treeitem", {
      name: /任务恢复/,
    })).toBeInTheDocument();
    fireEvent.click(recoveredEvent);
    expect(await screen.findByRole("heading", {
      name: "模型处理异常 · 已恢复",
    })).toBeInTheDocument();
    expect(screen.getByText("这一步曾发生异常，后续已恢复")).toBeInTheDocument();
  });

  it("refreshes a running trace until the atomic model response appears", async () => {
    let executionRequests = 0;
    let operationRequests = 0;
    let eventRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/settings/agent-diagnostics")) {
        return Response.json({ advancedEnabled: false, updatedAt: "2026-08-02T09:00:00Z" });
      }
      if (url.includes("/operations?")) {
        operationRequests += 1;
        return Response.json({
          items: operations.map((operation) => ({
            ...operation,
            status: operationRequests === 1 ? "running" : "completed",
            finishedAt: operationRequests === 1 ? null : operation.finishedAt,
          })),
        });
      }
      if (url.includes("/events?")) {
        eventRequests += 1;
        const items = [{
          eventId: "request-live",
          operationId: "model-1",
          eventType: "model.request",
          observedAt: "2026-08-02T09:00:00Z",
          byteLength: 800,
          sequence: 1,
        }];
        if (eventRequests > 1) {
          items.push({
            eventId: "response-live",
            operationId: "model-1",
            eventType: "model.response",
            observedAt: "2026-08-02T09:00:01Z",
            byteLength: 900,
            sequence: 2,
          });
        }
        return Response.json({ items });
      }
      if (url.includes("/api/agent-observability/executions/run-1?")) {
        executionRequests += 1;
        return Response.json({
          ...execution,
          status: executionRequests === 1 ? "running" : "completed",
          finishedAt: executionRequests === 1 ? null : execution.finishedAt,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });

    renderTrace();

    expect(await screen.findByRole("treeitem", { name: /模型请求/ })).toBeInTheDocument();
    expect(screen.queryByRole("treeitem", { name: /模型响应/ })).not.toBeInTheDocument();
    expect(await screen.findByRole("treeitem", { name: /模型响应/ }, { timeout: 2_500 })).toBeInTheDocument();
    expect(executionRequests).toBeGreaterThanOrEqual(2);
    expect(operationRequests).toBeGreaterThanOrEqual(2);
    expect(eventRequests).toBeGreaterThanOrEqual(2);
    const settledRequestCounts = {
      executionRequests,
      operationRequests,
      eventRequests,
    };
    await new Promise((resolve) => window.setTimeout(resolve, 1_100));
    expect({ executionRequests, operationRequests, eventRequests }).toEqual(settledRequestCounts);
  });

  it("treats a SQLite running start timestamp as UTC when showing live elapsed time", async () => {
    vi.spyOn(Date, "now").mockReturnValue(
      new Date("2026-08-02T09:00:23Z").getTime(),
    );
    mockTrace({
      ...execution,
      status: "running",
      startedAt: "2026-08-02 09:00:00",
      finishedAt: null,
      latencyMs: 0,
    });

    renderTrace();

    const metrics = await screen.findByRole("list", { name: "运行指标" });
    expect(within(metrics).getByText("23 秒")).toBeInTheDocument();
    expect(within(metrics).queryByText(/480/)).not.toBeInTheDocument();
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
