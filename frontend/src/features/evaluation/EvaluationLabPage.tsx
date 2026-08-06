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
  getObservabilityExecution,
  listObservabilityExecutions,
  listObservabilityOperations,
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
const TERMINAL_EXECUTION_STATUSES = [
  "completed",
  "failed",
  "cancelled",
  "interrupted",
] as const;

export function EvaluationLabPage({
  workspace,
}: {
  workspace: WorkspaceConfig | null;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const executionId = searchParams.get("executionId") ?? "";
  const legacyView = searchParams.get("view");
  const requestedSection = searchParams.get("section");
  const section = requestedSection === "regression" || requestedSection === "trends"
    ? requestedSection
    : "check";
  const reportOpen = legacyView === "tools"
    || searchParams.get("report") === "1"
    || section === "regression";
  const showOverview = section === "check" && !reportOpen;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [baselineId, setBaselineId] = useState<string>("");
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [showTechnicalMetrics, setShowTechnicalMetrics] = useState(false);
  const [judgeExecutionId, setJudgeExecutionId] = useState<string | null>(null);
  const [handledJudgeId, setHandledJudgeId] = useState<string | null>(null);
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
  const judgeExecutionQuery = useQuery({
    queryKey: ["agent-observability", "quality-check", workspace?.id, judgeExecutionId],
    enabled: Boolean(workspace && judgeExecutionId),
    queryFn: ({ signal }) => getObservabilityExecution(
      workspace!.id,
      judgeExecutionId!,
      signal,
    ),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_EXECUTION_STATUSES.some((item) => item === status)
        ? false
        : 1_000;
    },
  });
  const judgeOperationsQuery = useQuery({
    queryKey: ["agent-observability", "quality-check-operations", workspace?.id, judgeExecutionId],
    enabled: Boolean(workspace && judgeExecutionId),
    queryFn: ({ signal }) => listObservabilityOperations(
      workspace!.id,
      judgeExecutionId!,
      signal,
    ),
    refetchInterval: judgeExecutionQuery.data?.status === "running" ? 1_000 : false,
  });
  const judge = useMutation({
    mutationFn: () => createEvaluationRun(workspace!.id, executionId),
    onSuccess: (started) => {
      setHandledJudgeId(null);
      setJudgeExecutionId(started.judgeExecutionId);
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
  const sourceExecution = useMemo(
    () => (executionsQuery.data?.items ?? []).find((item) => item.id === executionId) ?? null,
    [executionId, executionsQuery.data?.items],
  );
  const sourceRun = useMemo(
    () => executionId ? runs.find((item) => item.executionId === executionId) ?? null : null,
    [executionId, runs],
  );
  useEffect(() => {
    if (executionId) {
      setSelectedId(sourceRun?.id ?? null);
      return;
    }
    if (selectedId && runs.some((item) => item.id === selectedId)) return;
    setSelectedId(runs[0]?.id ?? null);
  }, [executionId, runs, selectedId, sourceRun?.id]);
  const selected = useMemo(
    () => executionId ? sourceRun : runs.find((item) => item.id === selectedId) ?? null,
    [executionId, runs, selectedId, sourceRun],
  );
  const sourceSupportsEvaluation = Boolean(
    sourceExecution
      && (sourceExecution.evaluationSupported
        ?? sourceExecution.capabilities.includes("manual_judge")),
  );
  const sourceCanStartEvaluation = Boolean(
    sourceExecution
      && (sourceExecution.evaluationAvailable
        ?? sourceExecution.capabilities.includes("manual_judge")),
  );
  const judgeStatus = judgeExecutionQuery.data?.status ?? null;
  const judgeRunning = judge.isPending || judgeStatus === "running";
  useEffect(() => {
    if (
      !judgeExecutionId
      || !judgeStatus
      || !TERMINAL_EXECUTION_STATUSES.some((item) => item === judgeStatus)
      || handledJudgeId === judgeExecutionId
    ) return;
    setHandledJudgeId(judgeExecutionId);
    void queryClient.invalidateQueries({
      queryKey: ["agent-evaluations", workspace?.id],
    });
    void queryClient.invalidateQueries({
      queryKey: ["agent-observability", "quality-overview", workspace?.id],
    });
  }, [
    handledJudgeId,
    judgeExecutionId,
    judgeStatus,
    queryClient,
    workspace?.id,
  ]);
  const comparableRuns = useMemo(
    () => selected ? runs.filter((item) => (
      item.id !== selected.id
      && item.evalPackId === selected.evalPackId
      && item.evalPackVersion === selected.evalPackVersion
      && item.evaluationContractVersion === selected.evaluationContractVersion
      && item.runKind === selected.runKind
    )) : [],
    [runs, selected],
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
    next.delete("view");
    next.set("section", "check");
    next.set("report", "1");
    if (nextExecutionId) next.set("executionId", nextExecutionId);
    setSearchParams(next);
    setCompareEnabled(false);
    setBaselineId("");
    setShowTechnicalMetrics(false);
  }

  function openSection(nextSection: "check" | "regression" | "trends") {
    const next = new URLSearchParams(searchParams);
    next.delete("view");
    next.set("section", nextSection);
    if (nextSection === "check") next.delete("report");
    else if (nextSection === "regression") next.set("report", "1");
    else next.delete("report");
    setSearchParams(next);
    setCompareEnabled(nextSection === "regression");
    setBaselineId("");
    setShowTechnicalMetrics(false);
  }

  return (
    <section className="evaluation-lab" aria-label="Agent 质量中心">
      <header className="evaluation-lab__header">
        <div>
          <span className="evaluation-lab__eyebrow">Agent 运行中心</span>
          <h1>Agent 质量中心</h1>
          <p>检查一次运行的业务结果，确认问题，并把真实案例沉淀为持续回归。</p>
        </div>
        <nav
          className="evaluation-lab__primary-tabs"
          role="tablist"
          aria-label="质量中心功能"
        >
          <button
            type="button"
            role="tab"
            aria-selected={section === "check"}
            onClick={() => openSection("check")}
          >
            <ClipboardCheck />
            <span><strong>质量检查</strong><small>检查一次运行</small></span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={section === "regression"}
            onClick={() => openSection("regression")}
          >
            <FlaskConical />
            <span><strong>回归实验</strong><small>复测真实案例</small></span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={section === "trends"}
            onClick={() => openSection("trends")}
          >
            <BarChart3 />
            <span><strong>质量趋势</strong><small>观察长期变化</small></span>
          </button>
        </nav>
      </header>

      {!workspace ? (
        <div className="evaluation-state">
          <Bot /><strong>请先选择工作区。</strong>
        </div>
      ) : runsQuery.isPending
        || (showOverview && executionsQuery.isPending) ? (
        <div className="evaluation-state">
          <LoaderCircle className="evaluation-spin" />
          <strong>正在读取运行质量</strong>
        </div>
      ) : runsQuery.isError
        || (showOverview && executionsQuery.isError) ? (
        <div className="evaluation-state evaluation-state--error">
          <AlertTriangle /><strong>无法读取运行质量</strong>
        </div>
      ) : section === "trends" ? (
        <EvaluationTrendsPanel
          points={trendsQuery.data ?? []}
          loading={trendsQuery.isPending}
          error={trendsQuery.isError}
        />
      ) : showOverview ? (
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
          {selected ? (
            <>
              <ol className="evaluation-check-flow" aria-label="质量检查步骤">
                <li data-state="done"><span>1</span><strong>{section === "regression" ? "选择案例" : "选择运行"}</strong></li>
                <li data-state="done"><span>2</span><strong>{section === "regression" ? "运行复测" : "查看结果"}</strong></li>
                <li data-state="current"><span>3</span><strong>{section === "regression" ? "比较变化" : "人工确认"}</strong></li>
              </ol>
              <section className="evaluation-source-context" aria-label="本次质量检查来源">
                <div>
                  <span>{executionId ? "来源运行" : "当前质量报告"}</span>
                  <strong>{sourceExecution?.title ?? sourceExecution?.displayName ?? runChoiceLabel(selected)}</strong>
                  {executionId ? <small>报告只显示这次运行的检查结果，不会自动切换到其他历史报告。</small> : null}
                </div>
                {executionId && sourceCanStartEvaluation ? (
                  <div className="evaluation-toolbar__judge">
                    <button
                      type="button"
                      disabled={judgeRunning}
                      onClick={() => judge.mutate()}
                    >
                      {judgeRunning
                        ? <LoaderCircle className="evaluation-spin" />
                        : <FlaskConical />}
                      {judgeRunning ? "检查进行中" : "开始质量检查"}
                    </button>
                  </div>
                ) : null}
              </section>
              {judgeExecutionId ? (
                <QualityCheckProgress
                  executionId={judgeExecutionId}
                  status={judgeStatus}
                  operations={judgeOperationsQuery.data ?? []}
                  loading={judgeExecutionQuery.isPending}
                />
              ) : null}
              {judge.isError ? <p className="evaluation-compare-error" role="alert">这次运行的质量检查没有完成：{judge.error.message}</p> : null}

              <section className="evaluation-toolbar" aria-label="质量报告设置">
                {!executionId ? (
                  <label>
                    <span>当前结果</span>
                    <SelectControl aria-label="当前结果" value={selectedId ?? ""} onChange={(event) => setSelectedId(event.target.value)}>
                      {runs.map((item) => <option key={item.id} value={item.id}>{runChoiceLabel(item)}</option>)}
                    </SelectControl>
                  </label>
                ) : <span className="evaluation-toolbar__hint">先看本次结论，需要排查时再查看检查明细。</span>}
                <div className="evaluation-toolbar__actions">
                  <button type="button" className="evaluation-toolbar__secondary" onClick={() => { setCompareEnabled((value) => !value); setBaselineId(""); }}>
                    <Scale />{compareEnabled ? "关闭结果对比" : "对比历史结果"}
                  </button>
                  <button type="button" className="evaluation-toolbar__secondary" onClick={() => setShowTechnicalMetrics((value) => !value)}>
                    <Wrench />{showTechnicalMetrics ? "收起检查明细" : "查看检查明细"}
                  </button>
                </div>
              </section>

              {compareEnabled ? (
                <section className="evaluation-compare-picker" aria-label="选择可对比的历史结果">
                  <label>
                    <span>对比对象</span>
                    <SelectControl aria-label="之前结果" value={baselineId} onChange={(event) => setBaselineId(event.target.value)}>
                      <option value="">选择同一检查标准的历史结果</option>
                      {comparableRuns.map((item) => <option key={item.id} value={item.id}>{runChoiceLabel(item)}</option>)}
                    </SelectControl>
                  </label>
                  {!comparableRuns.length ? <small>暂时没有使用相同标准和版本的历史结果。</small> : null}
                </section>
              ) : null}

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
                  {showTechnicalMetrics || baselineId ? (
                    <EvaluationMetricMatrix
                      baseline={comparedBaseline}
                      candidate={comparedCandidate ?? selected}
                      dimensionIds={compareQuery.data?.dimensionIds}
                    />
                  ) : null}
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
                  {section === "regression" ? (
                    <RegressionCasePanel
                      run={selected}
                      cases={casesQuery.data ?? []}
                      pending={createCase.isPending}
                      onCreate={(includeBodies) => createCase.mutate(includeBodies)}
                      regressionRuns={regressionRunsQuery.data ?? []}
                      runPending={runRegression.isPending}
                      onRun={(item) => runRegression.mutate(item)}
                    />
                  ) : null}
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
              <h2>{sourceExecution && !sourceSupportsEvaluation
                ? "这类运行暂不支持质量检查"
                : sourceExecution && !sourceCanStartEvaluation
                  ? "这次运行暂时不能开始检查"
                : sourceExecution
                  ? `${sourceExecution.title} 还没有质量报告`
                  : "还没有质量检查结果"}</h2>
              <p>{sourceExecution && !sourceSupportsEvaluation
                ? sourceExecution.evaluationUnavailableReason
                  ?? "该运行没有注册质量检查标准；仍可返回运行中心查看 Trace 和技术详情。"
                : sourceExecution && !sourceCanStartEvaluation
                  ? sourceExecution.evaluationUnavailableReason
                    ?? "运行完成后才能开始质量检查。"
                : executionId
                  ? "开始检查后，这里只展示当前来源运行的结果；不会用其他历史报告代替。"
                  : "可以从一次 Agent 运行开始检查，业务运行结果不会因此改变。"}</p>
              {judge.isError ? <p className="evaluation-tool-empty__error" role="alert">检查没有完成：{judge.error.message}</p> : null}
              {judgeExecutionId ? (
                <QualityCheckProgress
                  executionId={judgeExecutionId}
                  status={judgeStatus}
                  operations={judgeOperationsQuery.data ?? []}
                  loading={judgeExecutionQuery.isPending}
                />
              ) : executionId && sourceCanStartEvaluation ? (
                <button
                  type="button"
                  disabled={judgeRunning}
                  onClick={() => judge.mutate()}
                >
                  {judgeRunning ? "检查进行中" : "开始质量检查"}
                </button>
              ) : !executionId ? (
                <Link to="/agents">选择一次运行</Link>
              ) : null}
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

function QualityCheckProgress({
  executionId,
  status,
  operations,
  loading,
}: {
  executionId: string;
  status: string | null;
  operations: Array<{ kind: string; status: string }>;
  loading: boolean;
}) {
  const modelOperation = operations.find((item) => item.kind === "model");
  const failed = status === "failed"
    || status === "cancelled"
    || status === "interrupted";
  const completed = status === "completed";
  const currentStep = completed
    ? 3
    : modelOperation?.status === "completed"
      ? 2
      : modelOperation
        ? 1
        : 0;
  const labels = ["准备检查依据", "AI 检查业务结果", "保存质量报告"];
  return (
    <section className="evaluation-live-progress" aria-live="polite">
      <header>
        <span>{failed ? <AlertTriangle /> : <LoaderCircle className={completed ? "" : "evaluation-spin"} />}</span>
        <div>
          <strong>{failed
            ? "质量检查没有完成"
            : completed
              ? "质量检查已完成"
              : loading
                ? "正在读取检查进度"
                : labels[currentStep]}</strong>
          <small>这是实际执行阶段，离开页面不会中断任务。</small>
        </div>
        <Link to={`/agents/executions/${encodeURIComponent(executionId)}`}>
          在运行中心查看
        </Link>
      </header>
      <ol>
        {labels.map((label, index) => (
          <li
            key={label}
            data-state={failed && index === currentStep
              ? "error"
              : index < currentStep || completed
                ? "done"
                : index === currentStep
                  ? "current"
                  : "pending"}
          >
            <span>{index + 1}</span>{label}
          </li>
        ))}
      </ol>
    </section>
  );
}
