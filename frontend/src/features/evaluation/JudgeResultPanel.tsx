import { AlertTriangle, ShieldCheck } from "lucide-react";
import { SelectControl } from "../../shared/ui/SelectControl";
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
    return <p className="evaluation-empty">选择一次结果查看检查依据。</p>;
  }
  const summary = run.judgeSummary?.summary;
  const confidence = run.judgeSummary?.confidence;
  return (
    <div className="judge-result">
      <header>
        <div>
          <span>你的判断</span>
          <h2>检查说明与结果确认</h2>
        </div>
      </header>
      {run.errorCode ? (
        <p className="judge-result__warning">
          <AlertTriangle size={17} />
          AI 质量检查未完成：{run.errorCode}。基础规则检查结果仍已保留。
        </p>
      ) : null}
      {typeof summary === "string" ? (
        <section className="judge-result__summary">
          <ShieldCheck size={19} />
          <div>
            <strong>AI 质量检查摘要</strong>
            <p>{summary}</p>
            <small>
              置信度 {typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : "未提供"}
            </small>
          </div>
        </section>
      ) : null}
      {run.rawSnapshot || run.rawJudgeResult ? (
        <details className="judge-result__raw">
          <summary>高级诊断：AI 检查原始输入与输出</summary>
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
      <strong>你的判断</strong>
      <SelectControl name="verdict" aria-label="反馈结论" defaultValue="accurate">
        <option value="accurate">检查结论准确</option>
        <option value="incorrect">检查结论不准确</option>
        <option value="uncertain">暂不确定</option>
      </SelectControl>
      <input name="reason" aria-label="反馈说明" placeholder="补充证据或说明（可选）" />
      <button type="submit" disabled={pending}>{pending ? "正在保存…" : "确认判断"}</button>
    </form>
  );
}
