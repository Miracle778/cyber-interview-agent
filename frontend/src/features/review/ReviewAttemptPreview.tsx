import { ArrowLeft, BookOpenCheck, CheckCircle2, RotateCcw, SkipForward } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ReviewAttempt } from "./reviewTypes";

const resultLabel = {
  independent_mastery: "独立掌握",
  assisted_mastery: "提示后掌握",
  revealed: "查看过答案",
  skipped: "已跳过",
} as const;

const scoreLabel = {
  good: "掌握良好",
  partial: "部分掌握",
  poor: "需要加强",
} as const;

export function ReviewAttemptPreview({
  attempt,
  currentOrdinal,
  onBack,
}: {
  attempt: ReviewAttempt;
  currentOrdinal: number;
  onBack: () => void;
}) {
  const status = attempt.skipped
    ? "已跳过"
    : attempt.resultKind
      ? resultLabel[attempt.resultKind]
      : attempt.evaluation
        ? scoreLabel[attempt.evaluation.score]
        : "已完成";
  const latestAnswer = attempt.answerRevisions?.at(-1) ?? attempt.followUpAnswer ?? attempt.answer;
  const keyPoints = attempt.coverage ?? [];

  return (
    <section className="review-attempt-preview" aria-label={`回看第 ${attempt.ordinal} 题`}>
      <header>
        <div>
          <span><RotateCcw size={15} />回看已处理题目</span>
          <h2>{attempt.ordinal}. {attempt.questionSnapshot.title}</h2>
        </div>
        <strong className={attempt.skipped ? "is-skipped" : ""}>
          {attempt.skipped ? <SkipForward size={15} /> : <CheckCircle2 size={15} />}
          {status}
        </strong>
      </header>

      <div className="review-attempt-preview__body">
        <section>
          <span>题目原文</span>
          <p>{attempt.questionSnapshot.questionText}</p>
          {attempt.questionSnapshot.topics?.length ? <div className="review-attempt-preview__topics">{attempt.questionSnapshot.topics.map((topic) => <em key={topic}>{topic}</em>)}</div> : null}
        </section>

        <section>
          <span>你的回答</span>
          <p>{attempt.skipped ? "本题由你主动跳过，没有提交回答。" : latestAnswer || "没有保存到可展示的回答。"}</p>
        </section>

        <section>
          <span>评价结果</span>
          {attempt.evaluation ? <p>{attempt.evaluation.evidence}</p> : <p className="status-note">本题没有评价结果。</p>}
          {keyPoints.length ? <details><summary><BookOpenCheck size={15} />查看关键点覆盖（{keyPoints.length}）</summary><ul>{keyPoints.map((item) => <li key={item.point}><strong>{item.status === "covered" ? "已覆盖" : item.status === "partial" ? "部分覆盖" : "未覆盖"}</strong><span>{item.point}</span></li>)}</ul></details> : null}
        </section>

        {attempt.questionSnapshot.referenceAnswer ? <details className="review-attempt-preview__answer"><summary>查看参考答案</summary><p>{attempt.questionSnapshot.referenceAnswer}</p></details> : null}
      </div>

      <footer>
        <p>当前复习仍停留在第 {currentOrdinal} 题，回看不会改变答题进度。</p>
        <Button onClick={onBack}><ArrowLeft size={16} />返回当前第 {currentOrdinal} 题</Button>
      </footer>
    </section>
  );
}
