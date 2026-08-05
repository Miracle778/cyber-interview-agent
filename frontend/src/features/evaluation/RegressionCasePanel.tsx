import {
  Archive,
  CheckCircle2,
  CircleAlert,
  FlaskConical,
  LockKeyhole,
  PlayCircle,
  Plus,
} from "lucide-react";
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
          <div className="regression-panel__actions">
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                if (window.confirm("确认创建不含运行正文的历史结果案例？")) onCreate(false);
              }}
            >
              <Archive />保存历史结果案例
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                if (window.confirm("可回归案例会在本机保留该次 Agent 执行前的任务正文、领域数据和会话状态，仅用于隔离回归。确认保存吗？")) onCreate(true);
              }}
            >
              {pending ? <Archive className="evaluation-spin" /> : <Plus />}
              {pending ? "正在保存…" : "保存可回归案例"}
            </button>
          </div>
        ) : null}
      </header>
      <p className="regression-panel__privacy">
        <LockKeyhole />历史结果案例不含正文，只能重新质检；可回归案例会保留本机执行前快照，并在两个隔离沙箱中重新生成业务结果，不会写入正式工作区。
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
            ) : cases.map((item, index) => {
              const latestRun = regressionRuns.find((run) => run.caseId === item.id);
              return (
                <tr key={item.id}>
                  <td><strong>案例 {String(index + 1).padStart(2, "0")}</strong><small>{item.redactionSummary}</small></td>
                  <td><code>{item.executionId.slice(0, 12)}</code></td>
                  <td>{evaluationPackLabel(item.evalPackId)} · v{item.evalPackVersion}</td>
                  <td>{item.containsPrivateBodies ? "包含经确认的正文" : "正文已移除"}</td>
                  <td>{formatBeijingDateTime(item.createdAt) ?? "时间未知"}</td>
                  <td>
                    {item.runnable && onRun ? (
                      <button type="button" disabled={runPending} onClick={() => onRun(item)}>
                        <PlayCircle />使用当前 Agent 版本运行回归案例
                      </button>
                    ) : <small>{item.unavailableReason ?? "仅支持重新质检历史结果"}</small>}
                    {latestRun ? <RegressionRunSummary run={latestRun} /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RegressionRunSummary({ run }: { run: RegressionRun }) {
  const pairwiseWinner = typeof run.pairwiseResult?.winner === "string"
    ? run.pairwiseResult.winner
    : null;
  const baselineVersions = objectValue(run.isolationManifest, "baselineVersions");
  const candidateVersions = objectValue(run.isolationManifest, "candidateVersions");
  const completed = run.status === "completed";
  const statusLabel = completed
    ? "回归已完成"
    : run.status === "failed"
      ? "回归未完成"
      : "回归处理中";

  return (
    <div className={`regression-run-summary${completed ? " is-completed" : " is-warning"}`}>
      <div className="regression-run-summary__headline">
        {completed ? <CheckCircle2 /> : <CircleAlert />}
        <span>
          <strong>{statusLabel}</strong>
          <small>{pairwiseConclusion(pairwiseWinner)}</small>
        </span>
      </div>
      <details>
        <summary><FlaskConical />查看本次回归依据</summary>
        <dl>
          <div>
            <dt>来源配置</dt>
            <dd>{implementationLabel(run.baselineImplementationId)}<code>{versionSummary(baselineVersions)}</code></dd>
          </div>
          <div>
            <dt>当前配置</dt>
            <dd>{implementationLabel(run.candidateImplementationId)}<code>{versionSummary(candidateVersions)}</code></dd>
          </div>
          <div>
            <dt>运行隔离</dt>
            <dd>{run.isolationManifest.separateSandboxes === true ? "双沙箱" : "未确认"} · {run.isolationManifest.productionWrites === false ? "未写正式工作区" : "写入状态未确认"}</dd>
          </div>
          <div>
            <dt>基础设施</dt>
            <dd>{run.infrastructureFailures.length === 0
              ? "无异常"
              : `${run.infrastructureFailures.length} 个异常，结果仅供排查`}</dd>
          </div>
        </dl>
      </details>
    </div>
  );
}

function objectValue(source: Record<string, unknown>, key: string) {
  const value = source[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function versionSummary(versions: Record<string, unknown>) {
  const graph = typeof versions.graph === "string" ? versions.graph : "Graph 版本未知";
  const mode = versions.codeMode === "current_process" ? "当前进程代码" : "代码版本未知";
  return `${graph} · ${mode}`;
}

function implementationLabel(implementationId: string) {
  return implementationId === "current-runtime" ? "当前模型配置" : "案例来源模型配置";
}

function pairwiseConclusion(winner: string | null) {
  if (winner === "a" || winner === "baseline") return "盲评结论：来源配置略优";
  if (winner === "b" || winner === "candidate") return "盲评结论：当前配置略优";
  if (winner === "tie") return "盲评结论：整体持平";
  return "尚无可展示的盲评结论";
}
