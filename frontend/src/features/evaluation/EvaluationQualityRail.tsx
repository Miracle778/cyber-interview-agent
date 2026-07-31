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
    <aside className="evaluation-quality-rail" aria-labelledby="quality-result-title">
      <section className="evaluation-quality-rail__policy">
        <header>
          <span>结果说明</span>
          <h2 id="quality-result-title">检查结论</h2>
        </header>
        <ol>
          <li>
            <span><ShieldCheck /></span>
            <div>
              <strong>{run.evaluationContractVersion >= 2
                ? "确定性业务规则"
                : "评估证据完整性检查"}</strong>
              <p>{run.evaluationContractVersion >= 2
                ? "只根据领域事实检查可证明的不变量，当前仅告警。"
                : "检查本次质检所需的 Trace 证据是否完整。"}</p>
            </div>
          </li>
          <li>
            <span><Bot /></span>
            <div>
              <strong>AI 质量检查</strong>
              <p>提供质量建议，不替代你的最终判断。</p>
            </div>
          </li>
          <li>
            <span><UserCheck /></span>
            <div>
              <strong>你的判断</strong>
              <p>重要或不确定的结果由你最终确认。</p>
            </div>
          </li>
        </ol>
      </section>

      <section className="evaluation-quality-rail__result">
        <header>
          <h3>本次结果</h3>
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
        <h3>检查设置</h3>
        <dl>
          <div><dt>检查标准</dt><dd>{evaluationPackLabel(run.evalPackId)}</dd></div>
          <div><dt>版本</dt><dd>v{run.evalPackVersion}</dd></div>
          <div><dt>检查方式</dt><dd>{run.trigger === "manual" ? "手动检查" : run.trigger === "automatic" ? "自动检查" : "复测验证"}</dd></div>
          <div><dt>AI 检查</dt><dd>{run.judgeProviderModelId ? "已配置" : "未启用"}</dd></div>
        </dl>
        <p>运行正文默认不进入复测案例；这里只展示检查依据与结论。</p>
      </section>
    </aside>
  );
}
