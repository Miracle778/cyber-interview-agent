import { AlertTriangle, ShieldCheck } from "lucide-react";
import {
  dimensionLabel,
  dimensionOutcome,
  evaluationStatusMeta,
  formatEvaluationVersion,
} from "./evaluationPresentation";
import type { EvaluationFeedback, EvaluationRun } from "./evaluationTypes";


interface JudgeResultPanelProps {
  run: EvaluationRun | null;
  feedbackPending: boolean;
  feedback: EvaluationFeedback[];
  onFeedback: (
    verdict: "accurate" | "incorrect" | "uncertain",
    reason: string,
  ) => void;
}

export function JudgeResultPanel({
  run,
  feedbackPending,
  feedback,
  onFeedback,
}: JudgeResultPanelProps) {
  if (!run) {
    return <p className="evaluation-empty">选择一次评估查看维度证据。</p>;
  }
  const summary = run.judgeSummary?.summary;
  const confidence = run.judgeSummary?.confidence;
  const status = evaluationStatusMeta(run.status);
  return (
    <div className="judge-result">
      <header>
        <div>
          <span>评估配置</span>
          <h2>{formatEvaluationVersion(run)}</h2>
        </div>
        <span data-tone={status.tone}>{status.label}</span>
      </header>
      {run.errorCode ? (
        <p className="judge-result__warning">
          <AlertTriangle size={17} />
          Judge 调用失败：{run.errorCode}。确定性检查结果仍已保留。
        </p>
      ) : null}
      {typeof summary === "string" ? (
        <section className="judge-result__summary">
          <ShieldCheck size={19} />
          <div>
            <strong>Judge 摘要</strong>
            <p>{summary}</p>
            <small>
              置信度 {typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : "未提供"}
            </small>
          </div>
        </section>
      ) : null}
      <div className="judge-dimensions">
        {run.dimensions.map((dimension) => (
          <article key={`${dimension.source}:${dimension.dimensionId}`}>
            <header>
              <strong>{dimensionLabel(dimension.dimensionId)}</strong>
              <span data-tone={dimensionOutcome(dimension).tone}>
                {dimension.score === null ? dimensionOutcome(dimension).label : `${dimension.score} 分`}
              </span>
            </header>
            <p>{dimension.summary}</p>
            <dl>
              <div>
                <dt>事件证据</dt>
                <dd>{dimension.citedEventHashes.length ? dimension.citedEventHashes.map((hash) => hash.slice(0, 10)).join("、") : "无"}</dd>
              </div>
              <div>
                <dt>产物证据</dt>
                <dd>{dimension.citedArtifactHashes.length ? dimension.citedArtifactHashes.map((hash) => hash.slice(0, 10)).join("、") : "无"}</dd>
              </div>
            </dl>
            {dimension.risks.length ? <p className="judge-dimension__risk">{dimension.risks.join("；")}</p> : null}
          </article>
        ))}
      </div>
      {run.rawSnapshot || run.rawJudgeResult ? (
        <details className="judge-result__raw">
          <summary>高级诊断：Judge 原始输入与输出</summary>
          {run.rawSnapshot ? <pre>{JSON.stringify(run.rawSnapshot, null, 2)}</pre> : null}
          {run.rawJudgeResult ? <pre>{JSON.stringify(run.rawJudgeResult, null, 2)}</pre> : null}
        </details>
      ) : null}
      <FeedbackForm pending={feedbackPending} onSubmit={onFeedback} />
      {feedback.length > 0 ? (
        <section className="judge-feedback-history">
          <strong>反馈历史</strong>
          <ol>
            {feedback.map((item) => (
              <li key={item.id}>
                <span>v{item.version} · {item.verdict}</span>
                {item.reason ? <p>{item.reason}</p> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}

function FeedbackForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: JudgeResultPanelProps["onFeedback"];
}) {
  return (
    <form
      className="judge-feedback"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onSubmit(
          String(data.get("verdict")) as "accurate" | "incorrect" | "uncertain",
          String(data.get("reason") ?? ""),
        );
        event.currentTarget.reset();
      }}
    >
      <strong>人工反馈</strong>
      <select name="verdict" aria-label="反馈结论" defaultValue="accurate">
        <option value="accurate">评估准确</option>
        <option value="incorrect">评估不准确</option>
        <option value="uncertain">暂不确定</option>
      </select>
      <input name="reason" aria-label="反馈说明" placeholder="补充证据或说明（可选）" />
      <button type="submit" disabled={pending}>{pending ? "正在保存…" : "提交反馈"}</button>
    </form>
  );
}
