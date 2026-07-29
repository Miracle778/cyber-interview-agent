import { Archive, LockKeyhole } from "lucide-react";
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
      <header><h2>冻结回归样例</h2><span>{cases.length} 个</span></header>
      {run ? (
        <div className="regression-panel__create">
          <LockKeyhole size={18} />
          <p>将冻结执行元数据、Eval Pack 版本与证据哈希。默认移除 Trace 正文。</p>
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm("确认创建不含 Trace 正文的回归样例？")) onCreate(false);
            }}
          >
            {pending ? "正在冻结…" : "创建样例"}
          </button>
        </div>
      ) : null}
      <ul>
        {cases.map((item) => (
          <li key={item.id}>
            <Archive size={16} />
            <span>
              <strong>{item.evalPackId} · v{item.evalPackVersion}</strong>
              <small>{item.redactionSummary}</small>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
