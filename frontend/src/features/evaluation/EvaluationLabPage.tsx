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
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatBeijingDateTime } from "../../shared/time";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { WorkspaceConfig } from "../settings/settingsApi";
import {
  compareEvaluationRuns,
  createEvaluationRun,
  createRegressionCase,
  listEvaluationRuns,
  listEvaluationFeedback,
  listEvaluationTrends,
  listRegressionCases,
  submitEvaluationFeedback,
} from "./evaluationApi";
import { EvaluationMetricMatrix } from "./EvaluationMetricMatrix";
import {
  evaluationPackLabel,
  evaluationStatusMeta,
} from "./evaluationPresentation";
import { EvaluationQualityRail } from "./EvaluationQualityRail";
import { EvaluationReportHeader } from "./EvaluationReportHeader";
import type { EvaluationRun } from "./evaluationTypes";
import { JudgeResultPanel } from "./JudgeResultPanel";
import { RegressionCasePanel } from "./RegressionCasePanel";
import { EvaluationTrendsPanel } from "./EvaluationTrendsPanel";
import "./evaluation.css";


export function EvaluationLabPage({
  workspace,
}: {
  workspace: WorkspaceConfig | null;
}) {
  const [searchParams] = useSearchParams();
  const executionId = searchParams.get("executionId") ?? "";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [baselineId, setBaselineId] = useState<string>("");
  const [activeView, setActiveView] = useState<"report" | "trends">("report");
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["agent-evaluations", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listEvaluationRuns(workspace!.id, undefined, signal),
  });
  const casesQuery = useQuery({
    queryKey: ["agent-regression-cases", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listRegressionCases(workspace!.id, signal),
  });
  const trendsQuery = useQuery({
    queryKey: ["agent-evaluation-trends", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) => listEvaluationTrends(workspace!.id, undefined, undefined, signal),
  });
  const judge = useMutation({
    mutationFn: () => createEvaluationRun(workspace!.id, executionId),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["agent-evaluations", workspace?.id] });
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
    }) => submitEvaluationFeedback(workspace!.id, selectedId!, verdict, reason),
  });
  const createCase = useMutation({
    mutationFn: (includePrivateBodies: boolean) =>
      createRegressionCase(workspace!.id, selectedId!, includePrivateBodies),
    onSuccess: () => void queryClient.invalidateQueries({
      queryKey: ["agent-regression-cases", workspace?.id],
    }),
  });
  const compareQuery = useQuery({
    queryKey: ["agent-evaluation-comparison", workspace?.id, baselineId, selectedId],
    enabled: Boolean(workspace && baselineId && selectedId && baselineId !== selectedId),
    queryFn: ({ signal }) =>
      compareEvaluationRuns(workspace!.id, [baselineId, selectedId!], signal),
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
    if (baselineId === selectedId || !runs.some((item) => item.id === baselineId)) {
      setBaselineId("");
    }
  }, [baselineId, runs, selectedId]);
  const comparedBaseline = compareQuery.data?.runs.find((item) => item.id === baselineId) ?? null;
  const comparedCandidate = compareQuery.data?.runs.find((item) => item.id === selectedId) ?? selected;
  const feedbackQuery = useQuery({
    queryKey: ["agent-evaluation-feedback", workspace?.id, selectedId],
    enabled: Boolean(workspace && selectedId),
    queryFn: ({ signal }) =>
      listEvaluationFeedback(workspace!.id, selectedId!, signal),
  });

  return (
    <section className="evaluation-lab" aria-label="Agent 质量实验室">
      <header className="evaluation-lab__header">
        <div>
          <h1>Agent 质量实验室</h1>
          <p>用冻结证据评估 Agent 输出，记录人工反馈并沉淀回归样例。</p>
        </div>
        <nav aria-label="Agent 工作区">
          <Link to="/agents">运行中心</Link>
          <Link to="/agents/evaluations" aria-current="page">质量评估</Link>
        </nav>
      </header>
      <div className="evaluation-lab__tabs" role="tablist" aria-label="质量实验室视图">
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "report"}
          onClick={() => setActiveView("report")}
        >
          <ClipboardCheck />评估报告
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "trends"}
          onClick={() => setActiveView("trends")}
        >
          <BarChart3 />长期趋势
        </button>
      </div>
      {!workspace ? (
        <div className="evaluation-state"><Bot /><strong>请先选择工作区。</strong></div>
      ) : runsQuery.isPending ? (
        <div className="evaluation-state"><LoaderCircle className="evaluation-spin" /><strong>正在读取质量评估</strong></div>
      ) : runsQuery.isError ? (
        <div className="evaluation-state evaluation-state--error"><AlertTriangle /><strong>无法读取质量评估</strong></div>
      ) : (
        <>
          {activeView === "trends" ? (
            <EvaluationTrendsPanel
              points={trendsQuery.data ?? []}
              loading={trendsQuery.isPending}
              error={trendsQuery.isError}
            />
          ) : selected ? (
            <>
              <section className="evaluation-toolbar" aria-label="评估对比设置">
                <div className="evaluation-toolbar__selectors">
                  <label>
                    <span>基线评估</span>
                    <SelectControl
                      aria-label="基线评估"
                      value={baselineId}
                      onChange={(event) => setBaselineId(event.target.value)}
                    >
                      <option value="">选择兼容基线</option>
                      {runs.filter((item) => item.id !== selectedId).map((item) => (
                        <option key={item.id} value={item.id}>{runChoiceLabel(item)}</option>
                      ))}
                    </SelectControl>
                  </label>
                  <Scale aria-hidden="true" />
                  <label>
                    <span>候选评估</span>
                    <SelectControl
                      aria-label="候选评估"
                      value={selectedId ?? ""}
                      onChange={(event) => setSelectedId(event.target.value)}
                    >
                      {runs.map((item) => (
                        <option key={item.id} value={item.id}>{runChoiceLabel(item)}</option>
                      ))}
                    </SelectControl>
                  </label>
                </div>
                {executionId ? (
                  <div className="evaluation-toolbar__judge">
                    <small>当前来源运行 <code>{executionId.slice(0, 12)}</code></small>
                    <button type="button" disabled={judge.isPending} onClick={() => judge.mutate()}>
                      {judge.isPending ? <LoaderCircle className="evaluation-spin" /> : <FlaskConical />}
                      {judge.isPending ? "Judge 评估中…" : "发起 Judge"}
                    </button>
                  </div>
                ) : null}
                {judge.isError ? <small role="alert">{judge.error.message}</small> : null}
              </section>

              {baselineId && compareQuery.isError ? (
                <p className="evaluation-compare-error" role="alert">
                  这两次评估的质量包版本或维度不兼容。候选报告仍可查看，请改选同版本基线。
                </p>
              ) : baselineId && compareQuery.isPending ? (
                <p className="evaluation-compare-loading"><Scale size={17} />正在校验基线兼容性…</p>
              ) : null}

              <div className="evaluation-workbench">
                <main className="evaluation-report">
                  <EvaluationReportHeader run={selected} caseCount={casesQuery.data?.length ?? 0} />
                  <EvaluationMetricMatrix
                    baseline={comparedBaseline}
                    candidate={comparedCandidate ?? selected}
                    dimensionIds={compareQuery.data?.dimensionIds}
                  />
                  <section className="evaluation-sources" aria-labelledby="evaluation-sources-title">
                    <header>
                      <span>可信度来源</span>
                      <h2 id="evaluation-sources-title">评估来源</h2>
                    </header>
                    <div>
                      <article><ShieldCheck /><span><strong>确定性规则</strong><small>结构、终态与证据完整性</small></span></article>
                      <article><Bot /><span><strong>独立 Judge</strong><small>基于冻结证据的质量评分</small></span></article>
                      <article><UserCheck /><span><strong>人工反馈</strong><small>纠偏并沉淀真实判断</small></span></article>
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
                          queryKey: ["agent-evaluation-feedback", workspace?.id, selectedId],
                        }),
                      },
                    )}
                  />
                  <RegressionCasePanel
                    run={selected}
                    cases={casesQuery.data ?? []}
                    pending={createCase.isPending}
                    onCreate={(includeBodies) => createCase.mutate(includeBodies)}
                  />
                </main>
                <EvaluationQualityRail run={selected} feedback={feedbackQuery.data ?? []} />
              </div>
            </>
          ) : (
            <p className="evaluation-empty">还没有质量评估，可从一次 Agent 运行发起 Judge。</p>
          )}
        </>
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
