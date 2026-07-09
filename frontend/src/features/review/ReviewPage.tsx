import { useState } from "react";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { confirmReport, runReview, type ConfirmReportResponse, type ReviewRunResponse } from "./reviewApi";
import type { ReviewQuestion } from "./reviewTypes";

interface ReviewPageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  onReportMarkdownChange: (markdown: string) => void;
}

export function ReviewPage({
  workspace,
  draftQuestion,
  latestReportMarkdown,
  onReportMarkdownChange,
}: ReviewPageProps) {
  const [answer, setAnswer] = useState("");
  const [reviewResult, setReviewResult] = useState<ReviewRunResponse | null>(null);
  const [confirmedReport, setConfirmedReport] = useState<ConfirmReportResponse | null>(null);
  const [error, setError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);

  const activeReportMarkdown = reviewResult?.report_markdown ?? latestReportMarkdown;

  async function handleRunReview() {
    setError("");
    if (!draftQuestion) {
      setError("请先上传资料生成题库草稿");
      return;
    }
    const trimmedAnswer = answer.trim();
    if (!trimmedAnswer) {
      setError("请输入你的回答");
      return;
    }
    setIsSending(true);
    try {
      const result = await runReview({
        questions: [draftQuestion],
        settings: {
          selectedTopics: [],
          questionCount: 1,
          mode: "weak-point",
        },
        userAnswer: trimmedAnswer,
      });
      setReviewResult(result);
      setConfirmedReport(null);
      onReportMarkdownChange(result.report_markdown);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复习评估失败");
    } finally {
      setIsSending(false);
    }
  }

  async function handleConfirmReport() {
    setError("");
    if (!workspace || !activeReportMarkdown) {
      setError("请先生成报告");
      return;
    }
    setIsConfirming(true);
    try {
      const result = await confirmReport({
        workspacePath: workspace.workspacePath,
        reportMarkdown: activeReportMarkdown,
      });
      setConfirmedReport(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "确认报告失败");
    } finally {
      setIsConfirming(false);
    }
  }

  return (
    <section aria-labelledby="review-title">
      <h2 id="review-title">复习</h2>
      <section aria-label="复习会话">
        <h3>会话</h3>
        <p>{reviewResult ? "本轮复习" : "暂无会话"}</p>
      </section>
      <section aria-label="复习对话">
        <h3>复习对话</h3>
        {!draftQuestion ? <p>请先上传资料生成题库草稿</p> : null}
        {draftQuestion ? (
          <article aria-label="当前题目">
            <h4>{draftQuestion.title}</h4>
            <p>{draftQuestion.questionText}</p>
          </article>
        ) : null}
        <label htmlFor="reviewAnswer">
          <span>你的回答</span>
          <textarea
            id="reviewAnswer"
            name="reviewAnswer"
            value={answer}
            disabled={!draftQuestion || isSending}
            onChange={(event) => setAnswer(event.target.value)}
          />
        </label>
        <button type="button" onClick={handleRunReview} disabled={!draftQuestion || isSending}>
          发送回答
        </button>
      </section>
      <section aria-label="复习设置">
        <h3>复习设置</h3>
        <p>模式：weak-point</p>
        <p>题目数：1</p>
      </section>
      {reviewResult ? (
        <section aria-label="复习评估">
          <h3>复习评估</h3>
          <p>评分：{reviewResult.evaluation.score}</p>
          <p>缺失点：{reviewResult.evaluation.missing_key_points.join("、") || "无"}</p>
          <p>证据：{reviewResult.evaluation.evidence || "无"}</p>
          <pre>{reviewResult.report_markdown}</pre>
        </section>
      ) : null}
      {workspace && activeReportMarkdown ? (
        <button type="button" onClick={handleConfirmReport} disabled={isConfirming}>
          确认报告
        </button>
      ) : null}
      {confirmedReport ? (
        <section aria-label="报告写入结果">
          <p>报告：{confirmedReport.reportPath}</p>
          <p>掌握度：{confirmedReport.masteryPath}</p>
        </section>
      ) : null}
      {error ? <p>错误：{error}</p> : null}
    </section>
  );
}
