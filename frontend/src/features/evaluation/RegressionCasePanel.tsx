import { Archive, LockKeyhole, Plus } from "lucide-react";
import { formatBeijingDateTime } from "../../shared/time";
import { evaluationPackLabel } from "./evaluationPresentation";
import type { EvaluationRun, RegressionCase } from "./evaluationTypes";


interface RegressionCasePanelProps {
  run: EvaluationRun | null;
  cases: RegressionCase[];
  pending: boolean;
  onCreate: (includePrivateBodies: boolean) => void;
}

export function RegressionCasePanel({
  run,
  cases,
  pending,
  onCreate,
}: RegressionCasePanelProps) {
  return (
    <section className="regression-panel">
      <header>
        <div>
          <span>稳定性资产</span>
          <h2>回归案例</h2>
        </div>
        {run ? (
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm("确认创建不含 Trace 正文的回归样例？")) onCreate(false);
            }}
          >
            {pending ? <Archive className="evaluation-spin" /> : <Plus />}
            {pending ? "正在冻结…" : "创建案例"}
          </button>
        ) : null}
      </header>
      <p className="regression-panel__privacy">
        <LockKeyhole />默认只冻结执行元数据、质量包版本与证据哈希，移除 Trace 正文。
      </p>
      <div className="regression-panel__table-wrap">
        <table>
          <thead>
            <tr>
              <th>案例</th>
              <th>来源运行</th>
              <th>评估配置</th>
              <th>隐私状态</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr><td colSpan={5}>还没有回归案例，可从当前评估冻结第一条。</td></tr>
            ) : cases.map((item, index) => (
              <tr key={item.id}>
                <td><strong>案例 {String(index + 1).padStart(2, "0")}</strong><small>{item.redactionSummary}</small></td>
                <td><code>{item.executionId.slice(0, 12)}</code></td>
                <td>{evaluationPackLabel(item.evalPackId)} · v{item.evalPackVersion}</td>
                <td>{item.containsPrivateBodies ? "包含经确认的正文" : "正文已移除"}</td>
                <td>{formatBeijingDateTime(item.createdAt) ?? "时间未知"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
