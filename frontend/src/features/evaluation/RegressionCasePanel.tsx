import { Archive, LockKeyhole, PlayCircle, Plus } from "lucide-react";
import { formatBeijingDateTime } from "../../shared/time";
import { evaluationPackLabel } from "./evaluationPresentation";
import type { EvaluationRun, RegressionCase, RegressionRun } from "./evaluationTypes";


interface RegressionCasePanelProps {
  run: EvaluationRun | null;
  cases: RegressionCase[];
  pending: boolean;
  onCreate: (includePrivateBodies: boolean) => void;
  regressionRuns?: RegressionRun[];
  onRun?: (item: RegressionCase) => void;
  runPending?: boolean;
}

export function RegressionCasePanel({
  run,
  cases,
  pending,
  onCreate,
  regressionRuns = [],
  onRun,
  runPending = false,
}: RegressionCasePanelProps) {
  return (
    <section className="regression-panel">
      <header>
        <div>
          <span>历史复检与真实回归</span>
          <h2>评估案例</h2>
        </div>
        {run ? (
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm("确认创建不含运行正文的复测案例？")) onCreate(false);
            }}
          >
            {pending ? <Archive className="evaluation-spin" /> : <Plus />}
            {pending ? "正在保存…" : "保存历史结果案例"}
          </button>
        ) : null}
      </header>
      <p className="regression-panel__privacy">
        <LockKeyhole />默认案例只用于重新质检历史结果；只有冻结了执行前领域状态且同时注册基线、候选实现时，才可运行真实 Agent 回归。
      </p>
      <div className="regression-panel__table-wrap">
        <table>
          <thead>
            <tr>
              <th>案例</th>
              <th>来源运行</th>
              <th>检查标准</th>
              <th>隐私状态</th>
              <th>创建时间</th>
              <th>可执行操作</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr><td colSpan={6}>还没有评估案例，可以从当前结果保存第一条。</td></tr>
            ) : cases.map((item, index) => (
              <tr key={item.id}>
                <td><strong>案例 {String(index + 1).padStart(2, "0")}</strong><small>{item.redactionSummary}</small></td>
                <td><code>{item.executionId.slice(0, 12)}</code></td>
                <td>{evaluationPackLabel(item.evalPackId)} · v{item.evalPackVersion}</td>
                <td>{item.containsPrivateBodies ? "包含经确认的正文" : "正文已移除"}</td>
                <td>{formatBeijingDateTime(item.createdAt) ?? "时间未知"}</td>
                <td>{item.runnable && onRun ? <button type="button" disabled={runPending} onClick={() => onRun(item)}><PlayCircle />使用当前 Agent 版本运行回归案例</button> : <small>{item.unavailableReason ?? "仅支持重新质检历史结果"}</small>}{regressionRuns.find((run) => run.caseId === item.id) ? <small>最近回归：{regressionRuns.find((run) => run.caseId === item.id)?.status}</small> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
