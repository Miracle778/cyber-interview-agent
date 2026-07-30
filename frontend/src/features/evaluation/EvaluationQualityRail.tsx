import {
  Bot,
  CheckCircle2,
  CircleAlert,
  GitPullRequestArrow,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import {
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
  return (
    <aside className="evaluation-quality-rail" aria-labelledby="quality-gate-title">
      <section className="evaluation-quality-rail__policy">
        <header>
          <span>发布策略</span>
          <h2 id="quality-gate-title">质量门禁</h2>
        </header>
        <ol>
          <li>
            <span><ShieldCheck /></span>
            <div>
              <strong>确定性规则</strong>
              <p>硬规则失败会阻止自动通过。</p>
            </div>
          </li>
          <li>
            <span><Bot /></span>
            <div>
              <strong>独立 Judge</strong>
              <p>提供质量信号，不单独替代业务决策。</p>
            </div>
          </li>
          <li>
            <span><UserCheck /></span>
            <div>
              <strong>人工反馈</strong>
              <p>高风险或不确定结果由人工确认。</p>
            </div>
          </li>
        </ol>
      </section>

      <section className="evaluation-quality-rail__result">
        <header>
          <h3>本次结果</h3>
          {summary.averageScore !== null ? <strong>{summary.averageScore}</strong> : null}
        </header>
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

      <section className="evaluation-quality-rail__config">
        <h3>评估配置</h3>
        <dl>
          <div><dt>质量包</dt><dd>{evaluationPackLabel(run.evalPackId)}</dd></div>
          <div><dt>版本</dt><dd>v{run.evalPackVersion}</dd></div>
          <div><dt>触发方式</dt><dd>{run.trigger === "manual" ? "手动评估" : run.trigger === "automatic" ? "自动评估" : "回归验证"}</dd></div>
          <div><dt>Judge 模型</dt><dd>{run.judgeProviderModelId ?? "未启用"}</dd></div>
        </dl>
        <p>原始正文默认不进入回归样例；这里只展示冻结证据与评估结论。</p>
      </section>
    </aside>
  );
}
