import { EvaluationMetricMatrix } from "./EvaluationMetricMatrix";
import { evaluationPackLabel } from "./evaluationPresentation";
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
        <span>{evaluationPackLabel(comparison.evalPackId)} · v{comparison.evalPackVersion}</span>
      </header>
      <EvaluationMetricMatrix
        baseline={comparison.runs[0] ?? null}
        candidate={comparison.runs[1] ?? comparison.runs[0]}
        dimensionIds={comparison.dimensionIds}
      />
    </section>
  );
}
