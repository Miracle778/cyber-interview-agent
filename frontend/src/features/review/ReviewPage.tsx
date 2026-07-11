import { useState } from "react";
import { AlertCircle, ClipboardCheck, FileCheck, Inbox, MessageSquareText } from "lucide-react";
import { Link } from "react-router-dom";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { confirmReport, runReview, type ConfirmReportResponse, type ReviewRunResponse } from "./reviewApi";
import type { ReviewQuestion } from "./reviewTypes";

interface ReviewPageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  onReportMarkdownChange: (markdown: string) => void;
  onReportConfirmed: () => void;
}

export function ReviewPage({
  workspace,
  draftQuestion,
  latestReportMarkdown,
  onReportMarkdownChange,
  onReportConfirmed,
}: ReviewPageProps) {
  const [answer, setAnswer] = useState("");
  const [reviewResult, setReviewResult] = useState<ReviewRunResponse | null>(null);
  const [confirmedReport, setConfirmedReport] = useState<ConfirmReportResponse | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);

  const activeReportMarkdown = reviewResult?.report_markdown ?? latestReportMarkdown;

  async function handleRunReview() {
    setError(null);
    if (!draftQuestion) {
      setError(toActionableError(new Error("请先上传资料生成题库草稿"), "复习评估失败"));
      return;
    }
    const trimmedAnswer = answer.trim();
    if (!trimmedAnswer) {
      setError(toActionableError(new Error("请输入你的回答"), "复习评估失败"));
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
      setError(toActionableError(caught, "复习评估失败"));
    } finally {
      setIsSending(false);
    }
  }

  async function handleConfirmReport() {
    setError(null);
    if (!workspace || !activeReportMarkdown) {
      setError(toActionableError(new Error("请先生成报告"), "确认报告失败"));
      return;
    }
    setIsConfirming(true);
    try {
      const result = await confirmReport({
        workspacePath: workspace.workspacePath,
        reportMarkdown: activeReportMarkdown,
      });
      setConfirmedReport(result);
      onReportConfirmed();
    } catch (caught) {
      setError(toActionableError(caught, "确认报告失败"));
    } finally {
      setIsConfirming(false);
    }
  }

  return (
    <section className="page-section" aria-labelledby="review-title">
      <div className="page-section__header">
        <span className="page-section__icon" aria-hidden="true">
          <MessageSquareText size={18} />
        </span>
        <h2 id="review-title" className="page-section__title">
          复习
        </h2>
        {draftQuestion ? <Badge tone="primary">weak-point · 1 题</Badge> : null}
      </div>

      <Card title="复习对话" icon={<MessageSquareText size={18} />}>
        {!draftQuestion ? (
          <div className="empty-state">
            <span className="empty-state__icon" aria-hidden="true">
              <Inbox size={20} />
            </span>
            <p className="empty-state__text">请先上传资料生成题库草稿</p>
            <Link className="text-link" to="/knowledge">
              前往知识库
            </Link>
          </div>
        ) : null}

        {draftQuestion ? (
          <article aria-label="当前题目">
            <h3 className="question-card__title">{draftQuestion.title}</h3>
            <p className="question-card__text">{draftQuestion.questionText}</p>
          </article>
        ) : null}

        <div className="field">
          <label className="field__label" htmlFor="reviewAnswer">
            你的回答
          </label>
          <textarea
            id="reviewAnswer"
            name="reviewAnswer"
            className="field__input field__input--area"
            value={answer}
            disabled={!draftQuestion || isSending}
            onChange={(event) => setAnswer(event.target.value)}
          />
        </div>

        <div className="btn-row">
          <Button onClick={handleRunReview} disabled={!draftQuestion || isSending} loading={isSending}>
            发送回答
          </Button>
        </div>
      </Card>

      {reviewResult ? (
        <Card title="复习评估" icon={<ClipboardCheck size={18} />} ariaLabel="复习评估">
          <p className="eval-score" data-score={reviewResult.evaluation.score}>
            评分：{reviewResult.evaluation.score}
          </p>
          <p className="eval-line">缺失点：{reviewResult.evaluation.missing_key_points.join("、") || "无"}</p>
          <p className="eval-line">证据：{reviewResult.evaluation.evidence || "无"}</p>

          <div>
            <p className="muted-text" style={{ marginBottom: "var(--space-2)" }}>
              报告预览
            </p>
            <pre className="report-preview">{reviewResult.report_markdown}</pre>
          </div>
        </Card>
      ) : null}

      {workspace && activeReportMarkdown ? (
        <Card title="确认报告" icon={<FileCheck size={18} />}>
          <p className="muted-text">将本轮报告与掌握度写入 Vault。</p>
          <div className="btn-row">
            <Button onClick={handleConfirmReport} disabled={isConfirming} loading={isConfirming}>
              确认报告
            </Button>
          </div>
          {confirmedReport ? (
            <div>
              <p className="result-line">报告：{confirmedReport.reportPath}</p>
              <p className="result-line">掌握度：{confirmedReport.masteryPath}</p>
            </div>
          ) : null}
        </Card>
      ) : null}

      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>错误：{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}
    </section>
  );
}
