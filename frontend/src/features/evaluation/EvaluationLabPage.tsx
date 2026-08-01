import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  ClipboardCheck,
  FlaskConical,
  LoaderCircle,
  Scale,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatBeijingDateTime } from "../../shared/time";
import { SelectControl } from "../../shared/ui/SelectControl";
import {
  listObservabilityExecutions,
} from "../observability/observabilityApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import {
  compareEvaluationRuns,
  createEvaluationRun,
  createRegressionCase,
  listEvaluationRuns,
  listEvaluationFeedback,
  listEvaluationTrends,
  listRegressionCases,
  listRegressionRuns,
  runRegressionCase,
  submitEvaluationFeedback,
} from "./evaluationApi";
import { EvaluationMetricMatrix } from "./EvaluationMetricMatrix";
import { EvaluationOverview } from "./EvaluationOverview";
import {
  evaluationPackLabel,
  evaluationStatusMeta,
} from "./evaluationPresentation";
import { EvaluationQualityRail } from "./EvaluationQualityRail";
import { EvaluationReportHeader } from "./EvaluationReportHeader";
import type { EvaluationRun, RegressionCase } from "./evaluationTypes";
import { JudgeResultPanel } from "./JudgeResultPanel";
import { RegressionCasePanel } from "./RegressionCasePanel";
import { EvaluationTrendsPanel } from "./EvaluationTrendsPanel";
import "./evaluation.css";


const ALL_EXECUTION_FILTERS = {
  search: "",
  status: "",
  agentName: "",
  includeSystemAgents: false,
};

export function EvaluationLabPage({
  workspace,
}: {
  workspace: WorkspaceConfig | null;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const executionId = searchParams.get("executionId") ?? "";
  const surface = searchParams.get("view") === "tools" ? "tools" : "overview";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [baselineId, setBaselineId] = useState<string>("");
  const [toolView, setToolView] = useState<"report" | "trends">("report");
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["agent-evaluations", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listEvaluationRuns(workspace!.id, undefined, signal),
  });
  const executionsQuery = useQuery({
    queryKey: ["agent-observability", "quality-overview", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) =>
      listObservabilityExecutions(
        workspace!.id,
        ALL_EXECUTION_FILTERS,
        signal,
      ),
  });
  const casesQuery = useQuery({
    queryKey: ["agent-regression-cases", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listRegressionCases(workspace!.id, signal),
  });
  const regressionRunsQuery = useQuery({
    queryKey: ["agent-regression-runs", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listRegressionRuns(workspace!.id, signal),
  });
  const trendsQuery = useQuery({
    queryKey: ["agent-evaluation-trends", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) =>
      listEvaluationTrends(workspace!.id, undefined, undefined, signal),
  });
  const judge = useMutation({
    mutationFn: () => createEvaluationRun(workspace!.id, executionId),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({
        queryKey: ["agent-evaluations", workspace?.id],
      });
      setSelectedId(run.id);
    },
  });
  const feedback = useMutation({
    mutationFn: ({
      verdict,
      reason,
    }: {
      verdict: "accurate" | "incorrect" | "uncertain";
      reason: string;
    }) => submitEvaluationFeedback(
      workspace!.id,
      selectedId!,
      verdict,
      reason,
    ),
  });
  const createCase = useMutation({
    mutationFn: (includePrivateBodies: boolean) =>
      createRegressionCase(workspace!.id, selectedId!, includePrivateBodies),
    onSuccess: () => void queryClient.invalidateQueries({
      queryKey: ["agent-regression-cases", workspace?.id],
    }),
  });
  const runRegression = useMutation({
    mutationFn: (item: RegressionCase) => {
      const source = item.availableImplementationIds.find((id) =>
        id.startsWith("source-model-config"));
      const current = item.availableImplementationIds.find((id) =>
        id === "current-runtime");
      if (!source || !current) {
        throw new Error("该案例缺少来源配置或当前运行时实现");
      }
      return runRegressionCase(
        workspace!.id,
        item.id,
        source,
        current,
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({
      queryKey: ["agent-regression-runs", workspace?.id],
    }),
  });
  const compareQuery = useQuery({
    queryKey: [
      "agent-evaluation-comparison",
      workspace?.id,
      baselineId,
      selectedId,
    ],
    enabled: Boolean(
      workspace && baselineId && selectedId && baselineId !== selectedId,
    ),
    queryFn: ({ signal }) =>
      compareEvaluationRuns(
        workspace!.id,
        [baselineId, selectedId!],
        signal,
      ),
  });
  const runs = runsQuery.data ?? [];
  useEffect(() => {
    if (selectedId && runs.some((item) => item.id === selectedId)) return;
    setSelectedId(runs[0]?.id ?? null);
  }, [runs, selectedId]);
  const selected = useMemo(
    () => runs.find((item) => item.id === selectedId) ?? null,
    [runs, selectedId],
  );
  useEffect(() => {
    if (
      baselineId === selectedId
      || !runs.some((item) => item.id === baselineId)
    ) {
      setBaselineId("");
    }
  }, [baselineId, runs, selectedId]);
  const comparedBaseline = compareQuery.data?.runs.find(
    (item) => item.id === baselineId,
  ) ?? null;
  const comparedCandidate = compareQuery.data?.runs.find(
    (item) => item.id === selectedId,
  ) ?? selected;
  const feedbackQuery = useQuery({
    queryKey: ["agent-evaluation-feedback", workspace?.id, selectedId],
    enabled: Boolean(workspace && selectedId),
    queryFn: ({ signal }) =>
      listEvaluationFeedback(workspace!.id, selectedId!, signal),
  });

  function openTools(nextExecutionId?: string) {
    const next = new URLSearchParams(searchParams);
    next.set("view", "tools");
    if (nextExecutionId) next.set("executionId", nextExecutionId);
    setSearchParams(next);
    setToolView("report");
  }

  function openOverview() {
    const next = new URLSearchParams(searchParams);
    next.delete("view");
    setSearchParams(next, { replace: true });
  }

  return (
    <section className="evaluation-lab" aria-label="运行质量">
      <header className="evaluation-lab__header">
        <div>
          <h1>Agent 运行中心</h1>
          <p>跟进正在处理的事项，及时完成需要你的步骤。</p>
        </div>
        <button
          className="evaluation-lab__tool-toggle"
          type="button"
          onClick={() => surface === "overview" ? openTools() : openOverview()}
        >
          {surface === "overview" ? <Wrench /> : <BarChart3 />}
          {surface === "overview" ? "评估工具" : "返回质量概览"}
        </button>
        <nav aria-label="Agent 运行中心工作区">
          <Link to="/agents">运行中心</Link>
          <Link to="/agents/evaluations" aria-current="page">运行质量</Link>
        </nav>
      </header>

      {!workspace ? (
        <div className="evaluation-state">
          <Bot /><strong>请先选择工作区。</strong>
        </div>
      ) : runsQuery.isPending
        || (surface === "overview" && executionsQuery.isPending) ? (
        <div className="evaluation-state">
          <LoaderCircle className="evaluation-spin" />
          <strong>正在读取运行质量</strong>
        </div>
      ) : runsQuery.isError
        || (surface === "overview" && executionsQuery.isError) ? (
        <div className="evaluation-state evaluation-state--error">
          <AlertTriangle /><strong>无法读取运行质量</strong>
        </div>
      ) : surface === "overview" ? (
        <EvaluationOverview
          runs={runs}
          executions={executionsQuery.data?.items ?? []}
          feedback={feedbackQuery.data ?? []}
          regressionCases={casesQuery.data ?? []}
          onSelectEvaluation={setSelectedId}
          onOpenTools={openTools}
        />
      ) : (
        <div className="evaluation-tools">
          <div
            className="evaluation-lab__tabs"
            role="tablist"
            aria-label="评估工具视图"
          >
            <button
              type="button"
              role="tab"
              aria-selected={toolView === "report"}
              onClick={() => setToolView("report")}
            >
              <ClipboardCheck />质量报告
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={toolView === "trends"}
              onClick={() => setToolView("trends")}
            >
              <BarChart3 />质量趋势
            </button>
          </div>
          {toolView === "trends" ? (
            <EvaluationTrendsPanel
              points={trendsQuery.data ?? []}
              loading={trendsQuery.isPending}
              error={trendsQuery.isError}
            />
          ) : selected ? (
            <>
              <section className="evaluation-toolbar" aria-label="结果对比设置">
                <div className="evaluation-toolbar__selectors">
                  <label>
                    <span>之前结果</span>
                    <SelectControl
                      aria-label="之前结果"
                      value={baselineId}
                      onChange={(event) => setBaselineId(event.target.value)}
                    >
                      <option value="">选择可对比的结果</option>
                      {runs
                        .filter((item) => item.id !== selectedId)
                        .map((item) => (
                          <option key={item.id} value={item.id}>
                            {runChoiceLabel(item)}
                          </option>
                        ))}
                    </SelectControl>
                  </label>
                  <Scale aria-hidden="true" />
                  <label>
                    <span>当前结果</span>
                    <SelectControl
                      aria-label="当前结果"
                      value={selectedId ?? ""}
                      onChange={(event) => setSelectedId(event.target.value)}
                    >
                      {runs.map((item) => (
                        <option key={item.id} value={item.id}>
                          {runChoiceLabel(item)}
                        </option>
                      ))}
                    </SelectControl>
                  </label>
                </div>
                {executionId ? (
                  <div className="evaluation-toolbar__judge">
                    <small>来源运行已选定</small>
                    <button
                      type="button"
                      disabled={judge.isPending}
                      onClick={() => judge.mutate()}
                    >
                      {judge.isPending
                        ? <LoaderCircle className="evaluation-spin" />
                        : <FlaskConical />}
                      {judge.isPending ? "检查中…" : "开始质量检查"}
                    </button>
                  </div>
                ) : null}
                {judge.isError
                  ? <small role="alert">{judge.error.message}</small>
                  : null}
              </section>

              {baselineId && compareQuery.isError ? (
                <p className="evaluation-compare-error" role="alert">
                  这两次结果使用了不同的检查标准，暂时不能直接比较。当前报告仍可查看。
                </p>
              ) : baselineId && compareQuery.isPending ? (
                <p className="evaluation-compare-loading">
                  <Scale size={17} />正在确认结果是否可以比较…
                </p>
              ) : null}

              <div className="evaluation-workbench">
                <main className="evaluation-report">
                  <EvaluationReportHeader
                    run={selected}
                    caseCount={casesQuery.data?.length ?? 0}
                  />
                  <EvaluationMetricMatrix
                    baseline={comparedBaseline}
                    candidate={comparedCandidate ?? selected}
                    dimensionIds={compareQuery.data?.dimensionIds}
                  />
                  <section
                    className="evaluation-sources"
                    aria-labelledby="evaluation-sources-title"
                  >
                    <header>
                      <span>检查依据</span>
                      <h2 id="evaluation-sources-title">结论来自哪里</h2>
                    </header>
                    <div>
                      <article>
                        <ShieldCheck />
                        <span>
                          <strong>{selected.evaluationContractVersion >= 2
                            ? "确定性业务规则"
                            : "评估证据完整性检查"}</strong>
                          <small>{selected.evaluationContractVersion >= 2
                            ? "领域行、Receipt、hash 与状态不变量"
                            : "Trace 事件是否足够完成初版质检"}</small>
                        </span>
                      </article>
                      <article>
                        <Bot />
                        <span>
                          <strong>AI 质量检查</strong>
                          <small>基于现有依据给出质量建议</small>
                        </span>
                      </article>
                      <article>
                        <UserCheck />
                        <span>
                          <strong>你的判断</strong>
                          <small>记录真实使用后的确认结果</small>
                        </span>
                      </article>
                    </div>
                  </section>
                  <JudgeResultPanel
                    run={selected}
                    feedbackPending={feedback.isPending}
                    feedback={feedbackQuery.data ?? []}
                    onFeedback={(verdict, reason) => feedback.mutate(
                      { verdict, reason },
                      {
                        onSuccess: () => void queryClient.invalidateQueries({
                          queryKey: [
                            "agent-evaluation-feedback",
                            workspace?.id,
                            selectedId,
                          ],
                        }),
                      },
                    )}
                  />
                  <RegressionCasePanel
                    run={selected}
                    cases={casesQuery.data ?? []}
                    pending={createCase.isPending}
                    onCreate={(includeBodies) => createCase.mutate(includeBodies)}
                    regressionRuns={regressionRunsQuery.data ?? []}
                    runPending={runRegression.isPending}
                    onRun={(item) => runRegression.mutate(item)}
                  />
                </main>
                <EvaluationQualityRail
                  run={selected}
                  feedback={feedbackQuery.data ?? []}
                />
              </div>
            </>
          ) : (
            <section className="evaluation-tool-empty">
              <FlaskConical aria-hidden="true" />
              <h2>还没有质量检查结果</h2>
              <p>可以从一次 Agent 运行开始检查，业务运行结果不会因此改变。</p>
              {executionId ? (
                <button
                  type="button"
                  disabled={judge.isPending}
                  onClick={() => judge.mutate()}
                >
                  {judge.isPending ? "检查中…" : "开始质量检查"}
                </button>
              ) : (
                <Link to="/agents">选择一次运行</Link>
              )}
            </section>
          )}
        </div>
      )}
    </section>
  );
}

function runChoiceLabel(run: EvaluationRun) {
  return [
    evaluationPackLabel(run.evalPackId),
    `v${run.evalPackVersion}`,
    evaluationStatusMeta(run.status).label,
    formatBeijingDateTime(run.createdAt) ?? "时间未知",
  ].join(" · ");
}
