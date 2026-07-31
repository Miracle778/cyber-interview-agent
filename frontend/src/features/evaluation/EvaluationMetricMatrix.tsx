import { ChevronDown, ChevronRight, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Fragment, useState } from "react";
import {
  dimensionLabel,
  dimensionOutcome,
} from "./evaluationPresentation";
import type { EvaluationDimension, EvaluationRun } from "./evaluationTypes";


interface EvaluationMetricMatrixProps {
  baseline: EvaluationRun | null;
  candidate: EvaluationRun;
  dimensionIds?: string[];
}

const LOWER_IS_BETTER = /(retry|error|duplicate|latency|token)/i;

function findDimension(run: EvaluationRun | null, dimensionId: string) {
  return run?.dimensions.find((item) => item.dimensionId === dimensionId) ?? null;
}

function scoreText(dimension: EvaluationDimension | null): string {
  if (!dimension) return "—";
  return dimension.score === null
    ? dimensionOutcome(dimension).label
    : String(dimension.score);
}

function ScoreCell({ dimension }: { dimension: EvaluationDimension | null }) {
  const score = dimension?.score;
  const outcome = dimension ? dimensionOutcome(dimension) : null;
  return (
    <div className="evaluation-metric-score" data-tone={outcome?.tone ?? "neutral"}>
      <strong>{scoreText(dimension)}</strong>
      {score !== null && score !== undefined ? (
        <span aria-hidden="true">
          <i style={{ width: `${Math.max(0, Math.min(score, 100))}%` }} />
        </span>
      ) : null}
    </div>
  );
}

function EvidencePanel({
  label,
  dimension,
}: {
  label: string;
  dimension: EvaluationDimension | null;
}) {
  if (!dimension) {
    return (
      <section className="evaluation-metric-evidence">
        <strong>{label}</strong>
        <p>没有这个维度的评估结果。</p>
      </section>
    );
  }
  return (
    <section className="evaluation-metric-evidence">
      <header>
        <strong>{label}</strong>
        <span data-tone={dimensionOutcome(dimension).tone}>
          {dimension.score === null ? dimensionOutcome(dimension).label : `${dimension.score} 分`}
        </span>
      </header>
      <p>{dimension.summary}</p>
      <dl>
        <div>
          <dt>置信度</dt>
          <dd>{dimension.confidence === null ? "未提供" : `${Math.round(dimension.confidence * 100)}%`}</dd>
        </div>
        <div>
          <dt>事件证据</dt>
          <dd>{dimension.citedEventHashes.length
            ? dimension.citedEventHashes.map((hash) => hash.slice(0, 18)).join("、")
            : "无"}</dd>
        </div>
        <div>
          <dt>产物证据</dt>
          <dd>{dimension.citedArtifactHashes.length
            ? dimension.citedArtifactHashes.map((hash) => hash.slice(0, 18)).join("、")
            : "无"}</dd>
        </div>
      </dl>
      {dimension.risks.length ? (
        <div className="evaluation-metric-evidence__risks">
          <strong>风险提示</strong>
          <p>{dimension.risks.join("；")}</p>
        </div>
      ) : null}
    </section>
  );
}

export function EvaluationMetricMatrix({
  baseline,
  candidate,
  dimensionIds,
}: EvaluationMetricMatrixProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const ids = dimensionIds ?? Array.from(new Set([
    ...(baseline?.dimensions.map((item) => item.dimensionId) ?? []),
    ...candidate.dimensions.map((item) => item.dimensionId),
  ]));

  return (
    <section className="evaluation-metrics" aria-labelledby="evaluation-metrics-title">
      <header>
        <div>
          <span>质量维度</span>
          <h2 id="evaluation-metrics-title">检查结果对比</h2>
        </div>
        <small>{ids.length} 个可评估维度</small>
      </header>
      {!baseline ? (
        <p className="evaluation-metrics__baseline-empty">尚未选择可对比的之前结果</p>
      ) : null}
      <div className="evaluation-metrics__table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">指标</th>
              <th scope="col">之前</th>
              <th scope="col">这次</th>
              <th scope="col">变化</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((dimensionId) => {
              const baselineDimension = findDimension(baseline, dimensionId);
              const candidateDimension = findDimension(candidate, dimensionId);
              const baselineScore = baselineDimension?.score;
              const candidateScore = candidateDimension?.score;
              const delta = baselineScore !== null && baselineScore !== undefined
                && candidateScore !== null && candidateScore !== undefined
                ? candidateScore - baselineScore
                : null;
              const lowerIsBetter = LOWER_IS_BETTER.test(dimensionId);
              const improved = delta === null || delta === 0
                ? null
                : lowerIsBetter ? delta < 0 : delta > 0;
              const expanded = expandedId === dimensionId;
              return (
                <Fragment key={dimensionId}>
                  <tr className="evaluation-metric-row" data-expanded={expanded}>
                    <th scope="row">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => setExpandedId(expanded ? null : dimensionId)}
                      >
                        {expanded ? <ChevronDown /> : <ChevronRight />}
                        <span>
                          <strong>{dimensionLabel(dimensionId)}</strong>
                          <small>{candidateDimension?.source === "deterministic" ? "基础规则检查" : "AI 质量检查"}</small>
                        </span>
                      </button>
                    </th>
                    <td data-label="之前"><ScoreCell dimension={baselineDimension} /></td>
                    <td data-label="这次"><ScoreCell dimension={candidateDimension} /></td>
                    <td data-label="变化">
                      <span
                        className="evaluation-metric-delta"
                        data-tone={improved === null ? "neutral" : improved ? "success" : "danger"}
                      >
                        {delta === null || delta === 0
                          ? <Minus aria-label={delta === null ? "无可比数据" : "没有变化"} />
                          : improved
                            ? <TrendingUp aria-hidden="true" />
                            : <TrendingDown aria-hidden="true" />}
                        {delta === null ? "—" : `${delta > 0 ? "+" : ""}${delta}`}
                      </span>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="evaluation-metric-detail">
                      <td colSpan={4}>
                        <div>
                          {baseline ? <EvidencePanel label="之前的检查依据" dimension={baselineDimension} /> : null}
                          <EvidencePanel label="这次的检查依据" dimension={candidateDimension} />
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
