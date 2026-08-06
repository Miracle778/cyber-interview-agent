import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { EvaluationLabPage } from "./EvaluationLabPage";
import type { EvaluationRun } from "./evaluationTypes";


const workspace: WorkspaceConfig = {
  id: "workspace-1",
  displayName: "面试准备",
  workspacePath: "/tmp/interview",
  vaultPath: "/tmp/interview/vault",
};

const run: EvaluationRun = {
  id: "eval-1",
  workspaceId: "workspace-1",
  executionId: "execution-1",
  evalPackId: "review.v1",
  evalPackVersion: 1,
  evaluationContractVersion: 1,
  taskType: "legacy",
  runKind: "historical_review",
  trigger: "manual",
  status: "completed",
  frozenInputHash: "a".repeat(64),
  businessOutcomeHash: null,
  judgeDataScope: {},
  judgeProviderModelId: "model-1",
  errorCode: null,
  createdAt: "2026-07-30T00:00:00Z",
  startedAt: "2026-07-30T00:00:01Z",
  completedAt: "2026-07-30T00:00:02Z",
  dimensions: [
    {
      dimensionId: "key_point_coverage",
      source: "judge",
      status: "scored",
      applicability: "applicable",
      rating: null,
      severity: null,
      score: 86,
      confidence: 0.82,
      summary: "关键结论有事件证据支持",
      citedEventHashes: ["event-hash-1"],
      citedArtifactHashes: ["artifact-hash-1"],
      risks: [],
      evidenceGaps: [],
      evidenceRefs: [],
    },
  ],
  deterministicResult: { status: "passed" },
  judgeSummary: {
    confidence: 0.82,
    summary: "整体质量稳定",
    risks: [],
    humanReviewRequired: false,
  },
  judgeTraceRunId: null,
  rawSnapshot: null,
  rawJudgeResult: null,
};

const execution = {
  id: "execution-1",
  sessionId: "session-1",
  workspaceId: "workspace-1",
  graphId: "review.round",
  displayName: "复习助手",
  system: false,
  title: "复习轮次 · 10 题",
  status: "completed",
  traceHealth: "complete",
  capabilities: ["open_business", "manual_judge"],
  route: "/review",
  systemOperationCount: 3,
  modelCallCount: 2,
  totalTokens: 3200,
  contextCurrentTokens: 1400,
  contextThresholdTokens: 8000,
  latencyMs: 3200,
  retryCount: 0,
  createdAt: "2026-07-30T00:00:00Z",
  startedAt: "2026-07-30T00:00:00Z",
  finishedAt: "2026-07-30T00:00:03Z",
  errorCode: null,
};

function renderPage(
  entry = "/agents/evaluations?executionId=execution-1",
) {
  return render(
    <MemoryRouter
      initialEntries={[entry]}
    >
      <QueryClientProvider client={new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })}>
        <EvaluationLabPage workspace={workspace} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function mockEvaluationPage(
  runs = [run],
  executions = [execution],
  comparisonStatus = 200,
) {
  const requests: Array<{ url: string; method: string }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({ url, method });
    if (url.includes("/agent-observability/executions/judge-execution-1/operations")) {
      return Response.json({
        items: [{
          id: "model-op-1",
          runId: "judge-execution-1",
          parentOperationId: null,
          kind: "model",
          name: "quality_evaluation_judge",
          agentRole: "answer_evaluation",
          status: "completed",
          startedAt: "2026-07-30T00:00:04Z",
          finishedAt: "2026-07-30T00:00:05Z",
          latencyMs: 1000,
          retryCount: 0,
          errorCode: null,
          eventCount: 2,
        }],
      });
    }
    if (url.includes("/agent-observability/executions/judge-execution-1")) {
      return Response.json({
        ...execution,
        id: "judge-execution-1",
        sessionId: "quality-session-1",
        graphId: "quality.evaluate",
        displayName: "运行质量评估",
        title: "质量检查：复习轮次 · 10 题",
        system: true,
        status: "completed",
        capabilities: ["export_trace"],
        definitionSnapshot: {
          snapshotVersion: 1,
          legacy: false,
          agentId: "quality.evaluate",
          agentDefinitionVersion: "1",
          graphVersion: 1,
          builderKey: "quality_evaluation_agents",
          promptSchemaVersions: {},
          inputSchemaVersion: null,
          outputSchemaVersion: null,
          childComponents: [],
          modelRoles: ["answer_evaluation"],
          allowedTools: [],
          allowedScopes: [],
          toolsetDigest: null,
          modelBindingDigest: null,
          contextPolicyId: null,
          retryPolicyId: null,
          tracePolicyId: null,
          evalPackId: null,
          evalPackVersion: null,
        },
      });
    }
    if (url.includes("/agent-observability/executions?")) {
      return Response.json({
        items: executions,
        nextCursor: null,
        total: executions.length,
        statusCounts: {},
        agentCounts: {},
      });
    }
    if (url.includes("/feedback")) return Response.json([]);
    if (url.includes("/trends")) return Response.json({ items: [] });
    if (url.includes("/regression-cases")) return Response.json({ items: [] });
    if (url.includes("/comparisons")) {
      return comparisonStatus === 200
        ? Response.json({
          evalPackId: "review.v1",
          evalPackVersion: 1,
          dimensionIds: ["key_point_coverage"],
          runs,
        })
        : Response.json({ detail: "incompatible" }, { status: comparisonStatus });
    }
    if (method === "POST" && url.includes("/runs?")) {
      return Response.json({
        judgeExecutionId: "judge-execution-1",
        sourceExecutionId: "execution-1",
      });
    }
    return Response.json({ items: runs });
  });
  return requests;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EvaluationLabPage", () => {
  it("uses a clear quality-center workflow without an advanced-mode detour", async () => {
    const requests = mockEvaluationPage();

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "质量概览" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Agent 质量中心" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^质量检查/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /^回归实验/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^质量趋势/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "高级评估" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "运行中心" })).not.toBeInTheDocument();
    expect(screen.getAllByText("复习轮次 · 10 题").length).toBeGreaterThan(0);
    expect(screen.getAllByText("表现稳定").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(
      screen.getByRole("heading", { name: "这次运行表现怎么样" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看对应运行" })).toHaveAttribute(
      "href",
      "/agents/executions/execution-1",
    );
    fireEvent.click(screen.getByRole("button", { name: "关闭质量详情" }));
    expect(
      screen.queryByRole("heading", { name: "这次运行表现怎么样" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(
      screen.getByRole("heading", { name: "这次运行表现怎么样" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看检查依据" }));
    expect(screen.getByText("选择运行")).toBeInTheDocument();
    expect(screen.getByText("查看结果")).toBeInTheDocument();
    expect(screen.getByText("人工确认")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /确认无问题/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /确认有问题/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /暂不判断/ })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "反馈结论" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("之前结果")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "对比历史结果" }));
    expect(screen.getByLabelText("之前结果")).toBeInTheDocument();
    expect(screen.queryByLabelText("当前结果")).not.toBeInTheDocument();
    expect(screen.getByText("本次结论")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "评估案例" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "长期质量趋势" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /^质量趋势/ }));
    expect(
      screen.getByRole("heading", { name: "长期质量趋势" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /^质量检查/ }));
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    fireEvent.click(screen.getByRole("button", { name: "查看检查依据" }));
    fireEvent.click(screen.getByRole("button", { name: "查看检查明细" }));
    fireEvent.click(screen.getByRole("button", { name: /关键点覆盖/ }));
    expect(screen.getByText(/event-hash/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始质量检查" }));
    await waitFor(() => expect(
      requests.some((request) =>
        request.method === "POST"
        && request.url.includes("/api/agent-evaluations/runs?")
      ),
    ).toBe(true));
    expect(await screen.findByText("质量检查已完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "在运行中心查看" })).toHaveAttribute(
      "href",
      "/agents/executions/judge-execution-1",
    );
    fireEvent.click(screen.getByRole("tab", { name: /^回归实验/ }));
    expect(screen.getByRole("heading", { name: "评估案例" })).toBeInTheDocument();
    expect(screen.getByText("选择案例")).toBeInTheDocument();
    expect(screen.getByText("运行复测")).toBeInTheDocument();
    expect(screen.getByText("比较变化")).toBeInTheDocument();
  });

  it("keeps raw AI-check data hidden when backend does not disclose it", async () => {
    mockEvaluationPage();
    renderPage("/agents/evaluations?view=tools&executionId=execution-1");

    await screen.findByText("查看结果");
    expect(
      screen.queryByText("高级诊断：AI 检查原始输入与输出"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/cost/i)).not.toBeInTheDocument();
  });

  it("only offers history that uses the same evaluation contract", async () => {
    const baseline = {
      ...run,
      id: "eval-2",
      executionId: "execution-2",
      evalPackId: "profile.v1",
      createdAt: "2026-07-29T00:00:00Z",
    };
    const baselineExecution = {
      ...execution,
      id: "execution-2",
      sessionId: "session-2",
      displayName: "画像助手",
      title: "画像助手：Java 开发工程师",
      createdAt: "2026-07-29T00:00:00Z",
    };
    mockEvaluationPage(
      [run, baseline],
      [execution, baselineExecution],
      409,
    );

    renderPage("/agents/evaluations?view=tools&executionId=execution-1");
    await screen.findByText("查看结果");
    fireEvent.click(screen.getByRole("button", { name: "对比历史结果" }));
    expect(screen.getByText("暂时没有使用相同标准和版本的历史结果。")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /画像助手/ })).not.toBeInTheDocument();
  });

  it("shows v2 applicability labels without inventing a total score", async () => {
    const v2Run: EvaluationRun = {
      ...run,
      id: "eval-v2",
      evalPackId: "question-curation.v2",
      evalPackVersion: 2,
      evaluationContractVersion: 2,
      taskType: "question_curation",
      runKind: "historical_review",
      businessOutcomeHash: "b".repeat(64),
      judgeDataScope: { mode: "minimal_evaluation_view" },
      dimensions: [
        {
          ...run.dimensions[0],
          dimensionId: "source_answer_fidelity",
          score: null,
          applicability: "not_applicable",
          rating: null,
          severity: null,
          confidence: null,
          evidenceGaps: ["材料未提供原文答案"],
        },
        {
          ...run.dimensions[0],
          dimensionId: "model_completion_quality",
          score: null,
          applicability: "applicable",
          rating: "needs_review",
          severity: "medium",
          evidenceGaps: [],
        },
      ],
    };
    mockEvaluationPage([v2Run]);
    renderPage("/agents/evaluations?view=tools&executionId=execution-1");

    await screen.findByText("查看结果");
    fireEvent.click(screen.getByRole("button", { name: "查看检查明细" }));

    expect(screen.getByText("业务结果质检")).toBeInTheDocument();
    expect(screen.getByText("不适用")).toBeInTheDocument();
    expect(screen.getByText("建议复核")).toBeInTheDocument();
    expect(screen.queryByText("总分")).not.toBeInTheDocument();
  });

  it("explains unsupported runs and never offers a fake start action", async () => {
    const unsupported = {
      ...execution,
      id: "execution-system",
      sessionId: "session-system",
      displayName: "运行时维护",
      title: "Trace 索引维护",
      capabilities: ["export_trace"],
      system: true,
    };
    mockEvaluationPage([], [unsupported]);
    renderPage("/agents/evaluations");

    await screen.findByRole("heading", { name: "质量概览" });
    expect(screen.getByText("暂不支持检查")).toBeInTheDocument();
    expect(screen.getByText(/该运行没有声明人工质量检查能力/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始检查" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始质量检查" })).not.toBeInTheDocument();
  });

  it("distinguishes a supported Agent from a run that is not ready yet", async () => {
    const running = {
      ...execution,
      id: "execution-running",
      sessionId: "session-running",
      status: "running",
      capabilities: ["open_business", "cancel"],
      evaluationSupported: true,
      evaluationAvailable: false,
      evaluationUnavailableReason: "运行完成后才能开始质量检查",
    };
    mockEvaluationPage([], [running]);
    renderPage("/agents/evaluations");

    await screen.findByRole("heading", { name: "质量概览" });
    expect(screen.getByText("等待运行完成")).toBeInTheDocument();
    expect(screen.getByText("运行完成后才能开始质量检查")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始检查" })).not.toBeInTheDocument();
  });

  it("maps legacy tools links to the quality-check entrance", async () => {
    mockEvaluationPage();
    renderPage("/agents/evaluations?view=tools&executionId=execution-1");

    expect(await screen.findByText("查看结果")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^质量检查/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
