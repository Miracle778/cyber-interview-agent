import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, Bot, LoaderCircle, Scale } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { WorkspaceConfig } from "../settings/settingsApi";
import {
  compareEvaluationRuns,
  createEvaluationRun,
  createRegressionCase,
  listEvaluationRuns,
  listEvaluationFeedback,
  listRegressionCases,
  submitEvaluationFeedback,
} from "./evaluationApi";
import { EvaluationCompareView } from "./EvaluationCompareView";
import { EvaluationRunList } from "./EvaluationRunList";
import { JudgeResultPanel } from "./JudgeResultPanel";
import { RegressionCasePanel } from "./RegressionCasePanel";
import "./evaluation.css";


export function EvaluationLabPage({
  workspace,
}: {
  workspace: WorkspaceConfig | null;
}) {
  const [searchParams] = useSearchParams();
  const executionId = searchParams.get("executionId") ?? "";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
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
    queryKey: ["agent-evaluation-comparison", workspace?.id, compareIds],
    enabled: Boolean(workspace && compareIds.length === 2),
    queryFn: ({ signal }) =>
      compareEvaluationRuns(workspace!.id, compareIds, signal),
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
      {!workspace ? (
        <div className="evaluation-state"><Bot /><strong>请先选择工作区。</strong></div>
      ) : runsQuery.isPending ? (
        <div className="evaluation-state"><LoaderCircle className="evaluation-spin" /><strong>正在读取质量评估</strong></div>
      ) : runsQuery.isError ? (
        <div className="evaluation-state evaluation-state--error"><AlertTriangle /><strong>无法读取质量评估</strong></div>
      ) : (
        <>
          {executionId ? (
            <aside className="evaluation-launch">
              <Activity size={18} />
              <span>已选择 Execution <code>{executionId}</code></span>
              <button type="button" disabled={judge.isPending} onClick={() => judge.mutate()}>
                {judge.isPending ? "Judge 评估中…" : "发起 Judge"}
              </button>
              {judge.isError ? <small role="alert">{judge.error.message}</small> : null}
            </aside>
          ) : null}
          {compareIds.length === 2 ? (
            compareQuery.isError ? (
              <p className="evaluation-compare-error" role="alert">
                这两次评估的 Eval Pack 版本或维度不兼容，不能直接比较。
              </p>
            ) : compareQuery.data ? (
              <EvaluationCompareView comparison={compareQuery.data} />
            ) : (
              <p className="evaluation-compare-loading"><Scale size={17} />正在准备对比…</p>
            )
          ) : null}
          <TaskWorkspace className="evaluation-lab__workspace">
            <TaskWorkspacePane className="evaluation-lab__runs">
              <header><h2>评估运行</h2><span>{runs.length} 条</span></header>
              <EvaluationRunList
                runs={runs}
                selectedId={selectedId}
                compareIds={compareIds}
                onSelect={setSelectedId}
                onToggleCompare={(id) => setCompareIds((current) =>
                  current.includes(id)
                    ? current.filter((item) => item !== id)
                    : [...current, id].slice(-2)
                )}
              />
            </TaskWorkspacePane>
            <TaskWorkspacePane className="evaluation-lab__result">
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
            </TaskWorkspacePane>
            <TaskWorkspacePane className="evaluation-lab__cases">
              <RegressionCasePanel
                run={selected}
                cases={casesQuery.data ?? []}
                pending={createCase.isPending}
                onCreate={(includeBodies) => createCase.mutate(includeBodies)}
              />
            </TaskWorkspacePane>
          </TaskWorkspace>
        </>
      )}
    </section>
  );
}
