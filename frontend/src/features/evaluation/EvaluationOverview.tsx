import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  CircleMinus,
  Clock3,
  FileCheck2,
  HelpCircle,
  ShieldCheck,
  UserCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { formatBeijingDateTime } from "../../shared/time";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { ExecutionSummary } from "../observability/observabilityTypes";
import {
  dimensionOutcome,
  summarizeEvaluation,
} from "./evaluationPresentation";
import type {
  EvaluationFeedback,
  EvaluationRun,
  RegressionCase,
} from "./evaluationTypes";

type QualityState = "stable" | "attention" | "unchecked";

interface QualityOverviewItem {
  execution: ExecutionSummary;
  evaluation: EvaluationRun | null;
  state: QualityState;
  conclusion: string;
  issue: string;
  impact: string;
  advice: string;
}

interface EvaluationOverviewProps {
  runs: EvaluationRun[];
  executions: ExecutionSummary[];
  feedback: EvaluationFeedback[];
  regressionCases: RegressionCase[];
  onSelectEvaluation: (evaluationId: string | null) => void;
  onOpenTools: (executionId?: string) => void;
}

const QUALITY_META = {
  stable: {
    label: "表现稳定",
    icon: CheckCircle2,
    tone: "success",
  },
  attention: {
    label: "需要关注",
    icon: AlertTriangle,
    tone: "warning",
  },
  unchecked: {
    label: "尚未检查",
    icon: CircleMinus,
    tone: "neutral",
  },
} as const;

export function EvaluationOverview({
  runs,
  executions,
  feedback,
  regressionCases,
  onSelectEvaluation,
  onOpenTools,
}: EvaluationOverviewProps) {
  const [range, setRange] = useState("7");
  const [agent, setAgent] = useState("");
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(
    null,
  );
  const [detailOpen, setDetailOpen] = useState(true);
  const allItems = useMemo(
    () => buildQualityOverviewItems(runs, executions),
    [executions, runs],
  );
  const visibleItems = useMemo(() => {
    const cutoff = range === "all"
      ? null
      : Date.now() - Number(range) * 24 * 60 * 60 * 1000;
    return allItems.filter((item) => {
      if (agent && item.execution.displayName !== agent) return false;
      if (cutoff === null) return true;
      return new Date(item.execution.createdAt).getTime() >= cutoff;
    });
  }, [agent, allItems, range]);
  const agentNames = useMemo(
    () => [...new Set(allItems.map((item) => item.execution.displayName))].sort(),
    [allItems],
  );
  const counts = useMemo(
    () => visibleItems.reduce(
      (result, item) => ({
        ...result,
        [item.state]: result[item.state] + 1,
      }),
      { stable: 0, attention: 0, unchecked: 0 },
    ),
    [visibleItems],
  );
  const attentionItems = visibleItems.filter(
    (item) => item.state === "attention",
  );
  const trend = useMemo(
    () => buildQualityTrend(visibleItems),
    [visibleItems],
  );

  useEffect(() => {
    if (
      selectedExecutionId
      && visibleItems.some((item) => item.execution.id === selectedExecutionId)
    ) return;
    const next = attentionItems[0] ?? visibleItems[0] ?? null;
    setSelectedExecutionId(next?.execution.id ?? null);
    setDetailOpen(Boolean(next));
    onSelectEvaluation(next?.evaluation?.id ?? null);
  }, [
    attentionItems,
    onSelectEvaluation,
    selectedExecutionId,
    visibleItems,
  ]);

  const selected = visibleItems.find(
    (item) => item.execution.id === selectedExecutionId,
  ) ?? null;
  const selectedFeedback = selected?.evaluation
    ? feedback.filter((item) => item.evalRunId === selected.evaluation!.id)
    : [];
  const selectedCase = selected
    ? regressionCases.some(
      (item) => item.executionId === selected.execution.id,
    )
    : false;

  function selectItem(item: QualityOverviewItem) {
    setSelectedExecutionId(item.execution.id);
    setDetailOpen(true);
    onSelectEvaluation(item.evaluation?.id ?? null);
  }

  return (
    <div className="quality-overview">
      <main className="quality-overview__main">
        <section className="quality-overview__summary" aria-labelledby="quality-summary-title">
          <header>
            <div>
              <h2 id="quality-summary-title">质量概览</h2>
              <span
                className="quality-overview__health"
                data-tone={counts.attention === 0 ? "success" : "warning"}
              >
                {counts.attention === 0
                  ? <CheckCircle2 aria-hidden="true" />
                  : <AlertTriangle aria-hidden="true" />}
                {counts.attention === 0 ? "整体表现稳定" : `${counts.attention} 次运行需要关注`}
              </span>
            </div>
            <SelectControl
              aria-label="质量统计范围"
              value={range}
              onChange={(event) => setRange(event.target.value)}
            >
              <option value="7">过去 7 天</option>
              <option value="30">过去 30 天</option>
              <option value="all">全部时间</option>
            </SelectControl>
          </header>
          <ul className="quality-overview__metrics">
            {(["stable", "attention", "unchecked"] as const).map((state) => {
              const meta = QUALITY_META[state];
              const Icon = meta.icon;
              return (
                <li key={state} data-tone={meta.tone}>
                  <span><Icon aria-hidden="true" /></span>
                  <div>
                    <small>{meta.label}</small>
                    <strong>{counts[state]}</strong>
                    {state === "attention" ? <em>优先查看影响结果的问题</em> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <div className="quality-overview__middle">
          <section className="quality-trend" aria-labelledby="quality-trend-title">
            <header>
              <div>
                <h2 id="quality-trend-title">最近质量变化</h2>
                <HelpCircle aria-label="按运行创建时间汇总检查结论" />
              </div>
              <div className="quality-agent-filters" aria-label="Agent 筛选">
                <button
                  type="button"
                  aria-pressed={!agent}
                  onClick={() => setAgent("")}
                >
                  全部
                </button>
                {agentNames.slice(0, 5).map((name) => (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={agent === name}
                    onClick={() => setAgent(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </header>
            {trend.length ? (
              <>
                <div className="quality-trend__legend" aria-hidden="true">
                  <span data-tone="success">表现稳定</span>
                  <span data-tone="warning">需要关注</span>
                  <span data-tone="neutral">尚未检查</span>
                </div>
                <ol className="quality-trend__chart">
                  {trend.map((point) => {
                    const maximum = Math.max(
                      ...trend.map((item) => item.total),
                      1,
                    );
                    return (
                      <li key={point.key}>
                        <div
                          className="quality-trend__bar"
                          style={{ height: `${Math.max(18, (point.total / maximum) * 100)}%` }}
                          aria-label={`${point.label}：稳定 ${point.stable}，关注 ${point.attention}，未检查 ${point.unchecked}`}
                        >
                          <i
                            data-tone="neutral"
                            style={{ flexGrow: point.unchecked }}
                          />
                          <i
                            data-tone="warning"
                            style={{ flexGrow: point.attention }}
                          />
                          <i
                            data-tone="success"
                            style={{ flexGrow: point.stable }}
                          />
                        </div>
                        <span>{point.label}</span>
                      </li>
                    );
                  })}
                </ol>
              </>
            ) : (
              <p className="quality-overview__empty">当前范围还没有运行数据。</p>
            )}
          </section>

          <section className="quality-attention" aria-labelledby="quality-attention-title">
            <header>
              <h2 id="quality-attention-title">需要关注</h2>
              <span>{attentionItems.length}</span>
            </header>
            {attentionItems.length ? (
              <ul>
                {attentionItems.slice(0, 4).map((item) => {
                  const meta = QUALITY_META[item.state];
                  const Icon = meta.icon;
                  return (
                    <li key={item.execution.id}>
                      <span data-tone={meta.tone}><Icon aria-hidden="true" /></span>
                      <div>
                        <strong>{qualityTaskTitle(item.execution)}</strong>
                        <p>{item.issue}</p>
                        <small>
                          {item.execution.displayName} · {formatBeijingDateTime(
                            item.evaluation?.completedAt
                              ?? item.execution.finishedAt
                              ?? item.execution.createdAt,
                          )}
                        </small>
                      </div>
                      {item.evaluation ? (
                        <button type="button" onClick={() => selectItem(item)}>
                          查看详情
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onOpenTools(item.execution.id)}
                        >
                          前往检查
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="quality-overview__empty">
                <Check aria-hidden="true" />当前范围没有需要关注的运行。
              </p>
            )}
          </section>
        </div>

        <section className="quality-results" aria-labelledby="quality-results-title">
          <header>
            <h2 id="quality-results-title">最近检查结果</h2>
          </header>
          <div className="quality-results__table-wrap">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>Agent</th>
                  <th>检查结论</th>
                  <th>主要问题</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.length === 0 ? (
                  <tr>
                    <td colSpan={6}>当前范围还没有可展示的运行。</td>
                  </tr>
                ) : visibleItems.slice(0, 8).map((item) => (
                  <tr
                    key={item.execution.id}
                    data-selected={item.execution.id === selectedExecutionId}
                  >
                    <td><strong>{qualityTaskTitle(item.execution)}</strong></td>
                    <td>{item.execution.displayName}</td>
                    <td>
                      <span className="quality-result-status" data-tone={QUALITY_META[item.state].tone}>
                        {item.conclusion}
                      </span>
                    </td>
                    <td>{item.issue}</td>
                    <td>{formatBeijingDateTime(
                      item.evaluation?.completedAt
                        ?? item.execution.finishedAt
                        ?? item.execution.createdAt,
                    )}</td>
                    <td>
                      {item.evaluation ? (
                        <button type="button" onClick={() => selectItem(item)}>
                          查看详情
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onOpenTools(item.execution.id)}
                        >
                          开始检查
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {selected && detailOpen ? (
        <aside className="quality-detail" aria-labelledby="quality-detail-title">
          <header>
            <div>
              <h2 id="quality-detail-title">
                {selected.state === "stable"
                  ? "这次运行表现怎么样"
                  : "这次运行需要注意什么"}
              </h2>
              <button
                type="button"
                aria-label="关闭质量详情"
                onClick={() => {
                  setDetailOpen(false);
                  onSelectEvaluation(null);
                }}
              >
                <X aria-hidden="true" />
              </button>
            </div>
            <strong>{qualityTaskTitle(selected.execution)}</strong>
            <small>
              {selected.execution.displayName} · 更新于{" "}
              {formatBeijingDateTime(
                selected.evaluation?.completedAt
                  ?? selected.execution.finishedAt
                  ?? selected.execution.createdAt,
              )}
            </small>
          </header>
          <section>
            <h3>主要结论</h3>
            <p>{selected.issue}</p>
          </section>
          <section>
            <h3>影响</h3>
            <p>{selected.impact}</p>
          </section>
          <section>
            <h3>建议</h3>
            <p>{selected.advice}</p>
          </section>
          <section>
            <h3>检查结论来源</h3>
            <ul className="quality-detail__sources">
              <li>
                <Bot aria-hidden="true" />
                <span><strong>AI 质量检查</strong><small>
                  {selected.evaluation?.judgeSummary ? "已完成" : "未提供"}
                </small></span>
              </li>
              <li>
                <ShieldCheck aria-hidden="true" />
                <span><strong>基础规则检查</strong><small>
                  {selected.evaluation?.deterministicResult ? "已完成" : "未提供"}
                </small></span>
              </li>
              <li>
                <UserCheck aria-hidden="true" />
                <span><strong>你的判断</strong><small>
                  {selectedFeedback.length ? "已确认" : "待确认"}
                </small></span>
              </li>
              <li>
                <FileCheck2 aria-hidden="true" />
                <span><strong>复测案例</strong><small>
                  {selectedCase ? "已加入" : "待确认"}
                </small></span>
              </li>
            </ul>
          </section>
          <footer>
            <Link to={`/agents/executions/${selected.execution.id}`}>
              查看对应运行
            </Link>
            {selected.evaluation ? (
              <button
                type="button"
                onClick={() => onOpenTools(selected.execution.id)}
              >
                查看检查依据
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onOpenTools(selected.execution.id)}
              >
                开始质量检查
              </button>
            )}
          </footer>
        </aside>
      ) : null}
    </div>
  );
}

export function buildQualityOverviewItems(
  runs: EvaluationRun[],
  executions: ExecutionSummary[],
): QualityOverviewItem[] {
  const latestByExecution = new Map<string, EvaluationRun>();
  for (const run of runs) {
    const existing = latestByExecution.get(run.executionId);
    if (
      !existing
      || new Date(run.createdAt).getTime() > new Date(existing.createdAt).getTime()
    ) {
      latestByExecution.set(run.executionId, run);
    }
  }
  return [...executions]
    .sort(
      (left, right) =>
        new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime(),
    )
    .map((execution) => {
      const evaluation = latestByExecution.get(execution.id) ?? null;
      if (!evaluation || ["pending", "queued", "running"].includes(evaluation.status)) {
        return {
          execution,
          evaluation,
          state: "unchecked",
          conclusion: evaluation ? "检查进行中" : "尚未检查",
          issue: evaluation ? "质量检查仍在进行" : "尚未进行质量检查",
          impact: "当前还没有足够信息判断这次运行的质量。",
          advice: "可以开始质量检查，或稍后等待检查完成。",
        };
      }
      if (evaluation.status === "failed") {
        return {
          execution,
          evaluation,
          state: "attention",
          conclusion: "检查未完成",
          issue: evaluation.errorCode
            ? `质量检查未完成：${evaluation.errorCode}`
            : "质量检查未完成",
          impact: "本次运行仍可查看，但质量结论暂时不完整。",
          advice: "可以重新发起质量检查，业务运行结果不会因此改变。",
        };
      }
      const dimensions = evaluation.dimensions
        .map((dimension) => ({
          dimension,
          outcome: dimensionOutcome(dimension),
        }))
        .sort((left, right) => toneRank(right.outcome.tone) - toneRank(left.outcome.tone));
      const primary = dimensions[0];
      const summary = summarizeEvaluation(evaluation);
      const state = summary.failed > 0 || summary.attention > 0
        ? "attention"
        : "stable";
      return {
        execution,
        evaluation,
        state,
        conclusion: state === "stable" ? "表现稳定" : "需要关注",
        issue: state === "stable"
          ? "未发现明显质量问题"
          : primary?.dimension.risks[0]
            ?? primary?.dimension.summary
            ?? "部分质量维度需要进一步核对",
        impact: conciseQualityText(primary?.dimension.summary)
          || (state === "stable"
            ? "现有检查依据支持继续使用本次结果。"
            : "可能影响结果的准确性、完整性或可用性。"),
        advice: state === "stable"
          ? "可以继续使用本次结果；重要内容仍建议结合实际情况判断。"
          : "建议查看对应内容并补充缺失依据，再确认是否继续使用。",
      };
    });
}

function toneRank(tone: string) {
  if (tone === "danger") return 3;
  if (tone === "warning") return 2;
  if (tone === "neutral") return 1;
  return 0;
}

function buildQualityTrend(items: QualityOverviewItem[]) {
  const points = new Map<string, {
    key: string;
    label: string;
    stable: number;
    attention: number;
    unchecked: number;
    total: number;
  }>();
  for (const item of [...items].reverse()) {
    const date = new Date(item.execution.createdAt);
    const key = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
    const label = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
    const point = points.get(key) ?? {
      key,
      label,
      stable: 0,
      attention: 0,
      unchecked: 0,
      total: 0,
    };
    point[item.state] += 1;
    point.total += 1;
    points.set(key, point);
  }
  return [...points.values()].slice(-7);
}

function qualityTaskTitle(execution: ExecutionSummary) {
  const title = execution.title.trim();
  if (/^source_[0-9a-f-]+\.[a-z0-9]+$/i.test(title)) {
    return `${execution.displayName}任务`;
  }
  return title.replace(/\.(md|markdown|txt)$/i, "");
}

function conciseQualityText(value: string | undefined) {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  const sentences = normalized.match(/[^。！？!?]+[。！？!?]?/g) ?? [normalized];
  const concise = sentences.slice(0, 2).join("").trim();
  return concise.length > 90 ? `${concise.slice(0, 87)}…` : concise;
}
