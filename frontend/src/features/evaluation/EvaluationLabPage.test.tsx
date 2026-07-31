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

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/agents/evaluations?executionId=execution-1"]}
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
      return Response.json(run);
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
  it("starts with an approachable quality overview and preserves quality tools", async () => {
    const requests = mockEvaluationPage();

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "质量概览" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "运行中心" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "运行质量" })).toHaveAttribute(
      "aria-current",
      "page",
    );
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

    fireEvent.click(screen.getByRole("button", { name: "评估工具" }));
    expect(screen.getByRole("tab", { name: "质量报告" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "质量趋势" })).toBeInTheDocument();
    expect(screen.getByLabelText("之前结果")).toBeInTheDocument();
    expect(screen.getByLabelText("当前结果")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "检查结论" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "复测案例" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "长期质量趋势" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "质量趋势" }));
    expect(
      screen.getByRole("heading", { name: "长期质量趋势" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "质量报告" }));
    fireEvent.click(screen.getByRole("button", { name: /关键点覆盖/ }));
    expect(screen.getByText(/event-hash/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始质量检查" }));
    await waitFor(() => expect(
      requests.some((request) =>
        request.method === "POST"
        && request.url.includes("/api/agent-evaluations/runs?")
      ),
    ).toBe(true));
  });

  it("keeps raw AI-check data hidden when backend does not disclose it", async () => {
    mockEvaluationPage();
    renderPage();

    await screen.findByRole("heading", { name: "质量概览" });
    fireEvent.click(screen.getByRole("button", { name: "评估工具" }));
    expect(
      screen.queryByText("高级诊断：AI 检查原始输入与输出"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/cost/i)).not.toBeInTheDocument();
  });

  it("keeps the current report usable when previous results are incompatible", async () => {
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

    renderPage();
    await screen.findByRole("heading", { name: "质量概览" });
    fireEvent.click(screen.getByRole("button", { name: "评估工具" }));
    fireEvent.change(screen.getByLabelText("之前结果"), {
      target: { value: "eval-2" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "当前报告仍可查看",
    );
    expect(
      screen.getByRole("heading", { name: "检查结果对比" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("86").length).toBeGreaterThan(0);
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
    renderPage();

    await screen.findByRole("heading", { name: "质量概览" });
    fireEvent.click(screen.getByRole("button", { name: "评估工具" }));

    expect(screen.getByText("业务结果质检")).toBeInTheDocument();
    expect(screen.getByText("不适用")).toBeInTheDocument();
    expect(screen.getByText("建议复核")).toBeInTheDocument();
    expect(screen.queryByText("总分")).not.toBeInTheDocument();
  });
});
