import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useState } from "react";
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
  const [verdict, setVerdict] = useState<"accurate" | "incorrect" | "uncertain">("accurate");
  return (
    <form
      className="judge-feedback"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onSubmit(verdict, String(data.get("reason") ?? ""));
        event.currentTarget.reset();
      }}
    >
      <div className="judge-feedback__heading">
        <strong>这次检查说得对吗？</strong>
        <small>你的确认会被保存，并可沉淀为后续回归案例。</small>
      </div>
      <div className="judge-feedback__choices" role="radiogroup" aria-label="反馈结论">
        {([
          ["accurate", "确认无问题", "检查结论与实际结果一致"],
          ["incorrect", "确认有问题", "检查遗漏或判断错误"],
          ["uncertain", "暂不判断", "目前证据不足，稍后再确认"],
        ] as const).map(([value, label, description]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={verdict === value}
            onClick={() => setVerdict(value)}
          >
            <strong>{label}</strong>
            <small>{description}</small>
          </button>
        ))}
      </div>
      <input name="reason" aria-label="反馈说明" placeholder="补充证据或说明（可选）" />
      <button className="judge-feedback__submit" type="submit" disabled={pending}>
        {pending ? "正在保存…" : "保存我的判断"}
      </button>
    </form>
  );
}
