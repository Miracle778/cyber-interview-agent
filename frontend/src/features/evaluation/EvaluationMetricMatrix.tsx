import { ChevronDown, ChevronRight, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Fragment, useState } from "react";
import {
  dimensionLabel,
  dimensionOutcome,
  dimensionUserSummary,
  isRuntimeDimension,
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
  const runtimeDimension = isRuntimeDimension(dimension.dimensionId);
  return (
    <section className="evaluation-metric-evidence">
      <header>
        <strong>{label}</strong>
        <span data-tone={dimensionOutcome(dimension).tone}>
          {dimension.score === null ? dimensionOutcome(dimension).label : `${dimension.score} 分`}
        </span>
      </header>
      <p>{dimensionUserSummary(dimension)}</p>
      {!runtimeDimension && dimension.risks.length ? (
        <div className="evaluation-metric-evidence__risks">
          <strong>风险提示</strong>
          <p>{dimension.risks.join("；")}</p>
        </div>
      ) : null}
      {!runtimeDimension && dimension.evidenceGaps.length ? (
        <div className="evaluation-metric-evidence__risks">
          <strong>缺少的依据</strong>
          <p>{dimension.evidenceGaps.join("；")}</p>
        </div>
      ) : null}
      <details className="evaluation-metric-evidence__technical">
        <summary>查看技术证据</summary>
        {dimension.summary !== dimensionUserSummary(dimension) ? <p>{dimension.summary}</p> : null}
        {runtimeDimension && dimension.risks.length ? <p>风险记录：{dimension.risks.join("；")}</p> : null}
        {runtimeDimension && dimension.evidenceGaps.length ? <p>缺失记录：{dimension.evidenceGaps.join("；")}</p> : null}
        <dl>
          <div>
            <dt>置信度</dt>
            <dd>{dimension.confidence === null ? "未提供" : `${Math.round(dimension.confidence * 100)}%`}</dd>
          </div>
          <div>
            <dt>业务依据</dt>
            <dd>{dimension.evidenceRefs.length
              ? dimension.evidenceRefs.join("、")
              : "无"}</dd>
          </div>
          <div>
            <dt>事件记录</dt>
            <dd>{dimension.citedEventHashes.length
              ? dimension.citedEventHashes.map((hash) => hash.slice(0, 18)).join("、")
              : "无"}</dd>
          </div>
          <div>
            <dt>结果记录</dt>
            <dd>{dimension.citedArtifactHashes.length
              ? dimension.citedArtifactHashes.map((hash) => hash.slice(0, 18)).join("、")
              : "无"}</dd>
          </div>
        </dl>
      </details>
    </section>
  );
}

function MetricTable({
  ids,
  baseline,
  candidate,
  expandedId,
  onToggle,
}: {
  ids: string[];
  baseline: EvaluationRun | null;
  candidate: EvaluationRun;
  expandedId: string | null;
  onToggle: (dimensionId: string) => void;
}) {
  const hasBaseline = baseline !== null;
  return (
    <div className="evaluation-metrics__table-wrap">
      <table data-comparison={hasBaseline}>
        <thead>
          <tr>
            <th scope="col">检查内容</th>
            {hasBaseline ? <th scope="col">之前</th> : null}
            <th scope="col">本次结果</th>
            {hasBaseline ? <th scope="col">变化</th> : null}
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
                      onClick={() => onToggle(dimensionId)}
                    >
                      {expanded ? <ChevronDown /> : <ChevronRight />}
                      <span>
                        <strong>{dimensionLabel(dimensionId)}</strong>
                        <small>{candidateDimension?.source === "deterministic"
                          ? "系统自动核对"
                          : "AI 内容检查"}</small>
                      </span>
                    </button>
                  </th>
                  {hasBaseline ? <td data-label="之前"><ScoreCell dimension={baselineDimension} /></td> : null}
                  <td data-label="本次结果"><ScoreCell dimension={candidateDimension} /></td>
                  {hasBaseline ? (
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
                  ) : null}
                </tr>
                {expanded ? (
                  <tr className="evaluation-metric-detail">
                    <td colSpan={hasBaseline ? 4 : 2}>
                      <div data-comparison={hasBaseline}>
                        {hasBaseline ? <EvidencePanel label="之前的检查依据" dimension={baselineDimension} /> : null}
                        <EvidencePanel label="本次检查依据" dimension={candidateDimension} />
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
  const contentIds = ids.filter((dimensionId) => !isRuntimeDimension(dimensionId));
  const runtimeIds = ids.filter(isRuntimeDimension);
  const toggle = (dimensionId: string) => setExpandedId(
    expandedId === dimensionId ? null : dimensionId,
  );

  return (
    <section className="evaluation-metrics" aria-labelledby="evaluation-metrics-title">
      <header>
        <div>
          <span>检查明细</span>
          <h2 id="evaluation-metrics-title">每项结果说明</h2>
        </div>
        <small>{contentIds.length} 项内容检查</small>
      </header>
      {!baseline ? (
        <p className="evaluation-metrics__baseline-empty">当前只显示本次检查结果；开启历史对比后可查看变化。</p>
      ) : null}
      {contentIds.length ? (
        <MetricTable ids={contentIds} baseline={baseline} candidate={candidate} expandedId={expandedId} onToggle={toggle} />
      ) : <p className="evaluation-metrics__empty">本次没有额外的内容检查项。</p>}
      {runtimeIds.length ? (
        <details className="evaluation-metrics__runtime">
          <summary>
            <span><strong>系统可靠性检查（{runtimeIds.length}）</strong><small>任务归属、重复写入和结果追溯等保护项</small></span>
            <ChevronDown aria-hidden="true" />
          </summary>
          <MetricTable ids={runtimeIds} baseline={baseline} candidate={candidate} expandedId={expandedId} onToggle={toggle} />
        </details>
      ) : null}
    </section>
  );
}
