import {
  Bot,
  CheckCircle2,
  CircleAlert,
  GitPullRequestArrow,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import {
  dimensionOutcome,
  dimensionUserSummary,
  evaluationPackLabel,
  summarizeEvaluation,
} from "./evaluationPresentation";
import type { EvaluationFeedback, EvaluationRun } from "./evaluationTypes";


const VERDICT_LABELS = {
  accurate: "已确认准确",
  incorrect: "已标记不准确",
  uncertain: "仍需复核",
} as const;

export function EvaluationQualityRail({
  run,
  feedback,
}: {
  run: EvaluationRun;
  feedback: EvaluationFeedback[];
}) {
  const summary = summarizeEvaluation(run, feedback);
  const priorities = run.dimensions
    .map((item) => ({ item, outcome: dimensionOutcome(item) }))
    .filter(({ outcome }) => outcome.tone === "warning" || outcome.tone === "danger")
    .sort((left, right) => (
      Number(right.outcome.tone === "danger") - Number(left.outcome.tone === "danger")
    ))
    .slice(0, 3);
  const overall = summary.failed > 0
    ? { label: "需要处理", detail: "存在明确风险，建议先处理后再使用。", tone: "danger" }
    : summary.attention > 0
      ? { label: "建议核对", detail: "结果基本可用，但有部分内容需要确认。", tone: "warning" }
      : { label: "可以使用", detail: "当前检查未发现需要阻断的问题。", tone: "success" };
  return (
    <aside className="evaluation-quality-rail" aria-labelledby="quality-result-title">
      <section className="evaluation-quality-rail__result">
        <header>
          <span>本次结论</span>
          <h2 id="quality-result-title" data-tone={overall.tone}>{overall.label}</h2>
        </header>
        <p className="evaluation-quality-rail__summary">{overall.detail}</p>
        <ul>
          <li data-tone="success">
            <CheckCircle2 />
            <span><strong>{summary.passed} 项稳定</strong><small>已通过或表现稳定</small></span>
          </li>
          <li data-tone="warning">
            <CircleAlert />
            <span><strong>{summary.attention} 项关注</strong><small>建议补充证据</small></span>
          </li>
          <li data-tone="danger">
            <GitPullRequestArrow />
            <span><strong>{summary.failed} 项风险</strong><small>需要处理或复核</small></span>
          </li>
        </ul>
        {summary.humanVerdict ? (
          <p className="evaluation-quality-rail__verdict">
            人工结论：{VERDICT_LABELS[summary.humanVerdict]}
          </p>
        ) : null}
      </section>

      <section className="evaluation-quality-rail__priorities">
        <h3>优先处理</h3>
        {priorities.length ? (
          <ol>
            {priorities.map(({ item, outcome }) => (
              <li key={item.dimensionId} data-tone={outcome.tone}>
                <CircleAlert />
                <span>{dimensionUserSummary(item)}</span>
              </li>
            ))}
          </ol>
        ) : <p>没有需要优先处理的问题。</p>}
      </section>

      <details className="evaluation-quality-rail__policy">
        <summary>查看检查方式</summary>
        <ol>
          <li><span><ShieldCheck /></span><div><strong>{run.evaluationContractVersion >= 2 ? "确定性业务规则" : "证据完整性检查"}</strong><p>只根据当前可证明的运行事实给出结论。</p></div></li>
          <li><span><Bot /></span><div><strong>AI 质量检查</strong><p>提供建议，不替代你的最终判断。</p></div></li>
          <li><span><UserCheck /></span><div><strong>你的判断</strong><p>重要或不确定的结果由你最终确认。</p></div></li>
        </ol>
      </details>

      <details className="evaluation-quality-rail__config">
        <summary>查看检查设置</summary>
        <dl>
          <div><dt>检查标准</dt><dd>{evaluationPackLabel(run.evalPackId)}</dd></div>
          <div><dt>版本</dt><dd>v{run.evalPackVersion}</dd></div>
          <div><dt>检查方式</dt><dd>{run.trigger === "manual" ? "手动检查" : run.trigger === "automatic" ? "自动检查" : "复测验证"}</dd></div>
          <div><dt>AI 检查</dt><dd>{run.judgeProviderModelId ? "已配置" : "未启用"}</dd></div>
        </dl>
        <p>运行正文默认不进入复测案例；这里只展示检查依据与结论。</p>
      </details>
    </aside>
  );
}
