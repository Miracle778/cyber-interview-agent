import { Activity, AlertTriangle, BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";
import { SelectControl } from "../../shared/ui/SelectControl";
import { evaluationPackLabel } from "./evaluationPresentation";
import type { EvaluationTrendPoint } from "./evaluationTypes";


export function EvaluationTrendsPanel({
  points,
  loading = false,
  error = false,
}: {
  points: EvaluationTrendPoint[];
  loading?: boolean;
  error?: boolean;
}) {
  const versions = useMemo(
    () => [...new Set(points.map((item) => `${item.evalPackId}@${item.evalPackVersion}`))],
    [points],
  );
  const [selected, setSelected] = useState("");
  const visible = selected
    ? points.filter((item) => `${item.evalPackId}@${item.evalPackVersion}` === selected)
    : points;
  return (
    <section className="evaluation-trends" aria-labelledby="evaluation-trends-title">
      <header>
        <div><BarChart3 size={18} /><h2 id="evaluation-trends-title">长期质量趋势</h2></div>
        <label>
          <span>检查标准版本</span>
          <SelectControl value={selected} onChange={(event) => setSelected(event.target.value)}>
            <option value="">全部（分版本展示）</option>
            {versions.map((version) => <option key={version} value={version}>{version}</option>)}
          </SelectControl>
        </label>
      </header>
      {loading ? <p role="status"><Activity />正在汇总历史检查结果…</p> : null}
      {error ? <p role="alert"><AlertTriangle />无法读取质量趋势。</p> : null}
      {!loading && !error && visible.length === 0 ? (
        <p>还没有足够的评估数据形成趋势。</p>
      ) : null}
      {visible.length > 0 ? (
        <div className="evaluation-trends__table-wrap">
          <table>
            <thead>
              <tr>
                <th>日期</th><th>Agent / 版本</th><th>运行</th><th>成功率</th>
                <th>规则问题</th><th>AI 检查均分</th><th>人工复核</th>
                <th>平均耗时</th><th>Token / 上下文</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((point) => (
                <tr key={[
                  point.bucket,
                  point.graphId,
                  point.evalPackId,
                  point.evalPackVersion,
                  point.judgeProviderModelId,
                  point.promptVersion,
                  point.schemaVersion,
                  point.toolVersion,
                ].join(":")}>
                  <td>{point.bucket}</td>
                  <td><strong>{evaluationPackLabel(point.evalPackId)}</strong><small>标准版本 v{point.evalPackVersion}</small></td>
                  <td>{point.runCount}</td>
                  <td><Rate value={point.successRate} /></td>
                  <td><Rate value={point.deterministicIssueRate} inverse /></td>
                  <td>{point.averageJudgeScore === null ? "—" : point.averageJudgeScore.toFixed(1)}</td>
                  <td>{percent(point.humanReviewRate)}</td>
                  <td>{point.averageLatencyMs === null ? "—" : `${Math.round(point.averageLatencyMs / 1000)} 秒`}</td>
                  <td>{Math.round(point.averageTokens).toLocaleString()} / {Math.round(point.averageContextTokens).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Rate({ value, inverse = false }: { value: number; inverse?: boolean }) {
  return (
    <span className="evaluation-trend-rate" data-inverse={inverse}>
      <span style={{ width: percent(value) }} aria-hidden="true" />
      <strong>{percent(value)}</strong>
    </span>
  );
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}
