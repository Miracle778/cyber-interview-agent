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
          <span>重复验证</span>
          <h2>复测案例</h2>
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
            {pending ? "正在保存…" : "加入复测案例"}
          </button>
        ) : null}
      </header>
      <p className="regression-panel__privacy">
        <LockKeyhole />默认只保存运行摘要、检查标准版本与依据指纹，不保存运行正文。
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
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr><td colSpan={5}>还没有复测案例，可以从当前结果加入第一条。</td></tr>
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
