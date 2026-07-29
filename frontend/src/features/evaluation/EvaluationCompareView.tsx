import { Fragment } from "react";
import type { EvaluationComparison } from "./evaluationTypes";


export function EvaluationCompareView({
  comparison,
}: {
  comparison: EvaluationComparison;
}) {
  return (
    <section className="evaluation-compare" aria-label="评估对比">
      <header>
        <h2>版本对比</h2>
        <span>{comparison.evalPackId} · v{comparison.evalPackVersion}</span>
      </header>
      <div className="evaluation-compare__grid">
        <strong>维度</strong>
        {comparison.runs.map((run) => <strong key={run.id}>{run.id.slice(0, 8)}</strong>)}
        {comparison.dimensionIds.map((dimensionId) => (
          <Fragment key={dimensionId}>
            <span>{dimensionId}</span>
            {comparison.runs.map((run) => {
              const dimension = run.dimensions.find(
                (item) => item.source === "judge" && item.dimensionId === dimensionId,
              );
              return (
                <span key={`${dimensionId}:${run.id}`}>
                  {dimension?.score ?? "—"}
                  <small>{dimension?.summary ?? "无可比结果"}</small>
                </span>
              );
            })}
          </Fragment>
        ))}
      </div>
    </section>
  );
}
