import { BarChart3, FileCheck2, MessageCircle, MessagesSquare, PanelLeftClose } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import type { ReviewAttempt, ReviewRound } from "./reviewTypes";
import { ReviewChatMessage } from "./ReviewConversation";

type ResultsView = "questions" | "replay" | "discussions" | "reports";
type AttemptFilter = "all" | "completed" | "good" | "skipped";

const scoreText = { good: "掌握良好", partial: "部分掌握", poor: "需要加强" } as const;
const resultText = {
  independent_mastery: "独立掌握",
  assisted_mastery: "提示后掌握",
  revealed: "查看答案",
  skipped: "已跳过",
} as const;
const publicationText: Record<string, string> = {
  published: "已发布",
  completed: "已确认",
  review_pending: "待确认",
  index_stale: "索引待更新",
  failed: "发布失败",
};

function attemptResult(attempt: ReviewAttempt) {
  if (attempt.resultKind) return resultText[attempt.resultKind];
  if (attempt.skipped) return "已跳过";
  if (attempt.evaluation) return scoreText[attempt.evaluation.score];
  return "未评价";
}

export function ReviewResults({
  round,
  onDiscuss,
  onOpenApproval,
  activeApprovalReportId,
  selectedReportId,
  onCollapse,
  discussingOrdinal = null,
}: {
  round: ReviewRound;
  onDiscuss: (ordinal: number) => void;
  onOpenApproval?: (reportId?: string) => void;
  activeApprovalReportId?: string | null;
  selectedReportId?: string | null;
  onCollapse?: () => void;
  discussingOrdinal?: number | null;
}) {
  const good = round.attempts.filter((item) => item.evaluation?.score === "good").length;
  const completed = round.attempts.filter((item) => item.status === "completed").length;
  const skipped = round.attempts.filter((item) => item.skipped).length;
  const discussionCount = round.attempts.filter((item) => item.discussionSessionId).length;
  const [view, setView] = useState<ResultsView>("questions");
  const [filter, setFilter] = useState<AttemptFilter>("all");
  const [selectedOrdinal, setSelectedOrdinal] = useState<number | null>(round.attempts[0]?.ordinal ?? null);
  const activeReportIndex = round.reports.findIndex((report) => report.id === activeApprovalReportId);
  const visibleAttempts = round.attempts.filter((attempt) =>
    filter === "all"
    || (filter === "completed" && attempt.status === "completed")
    || (filter === "good" && attempt.evaluation?.score === "good")
    || (filter === "skipped" && attempt.skipped)
  );
  const selectedAttempt = visibleAttempts.find((attempt) => attempt.ordinal === selectedOrdinal)
    ?? visibleAttempts[0]
    ?? null;
  const replayMessages = round.messages.length ? round.messages : round.attempts.flatMap((attempt) => [
    { id: `${attempt.id}-prompt`, executionId: round.executionId, role: "assistant", content: attempt.questionSnapshot.questionText, messageKind: "review_prompt", payload: {}, createdAt: round.createdAt },
    { id: `${attempt.id}-answer`, executionId: round.executionId, role: "user", content: attempt.skipped ? "已跳过本题" : attempt.answer || "未作答", messageKind: "review_answer", payload: {}, createdAt: round.createdAt },
    ...(attempt.evaluation ? [{ id: `${attempt.id}-evaluation`, executionId: round.executionId, role: "assistant", content: attempt.evaluation.evidence, messageKind: "evaluation_card", payload: { evaluation: attempt.evaluation }, createdAt: round.updatedAt }] : []),
  ]);

  const startDiscussion = (attempt: ReviewAttempt) => (
    <Button
      size="sm"
      variant={attempt.discussionSessionId ? "secondary" : "primary"}
      loading={discussingOrdinal === attempt.ordinal}
      disabled={discussingOrdinal !== null}
      onClick={() => onDiscuss(attempt.ordinal)}
    >
      <MessageCircle size={14} />
      {attempt.discussionSessionId ? "继续讨论" : "深入讨论"}
    </Button>
  );

  return (
    <Card
      title="本轮复习结果"
      icon={<BarChart3 size={18} />}
      actions={onCollapse ? <button type="button" className="review-pane-collapse" aria-label="收起复习结果，展开报告确认" title="收起复习结果" onClick={onCollapse}><PanelLeftClose size={18} /></button> : undefined}
      className="review-results-card"
      bodyClassName="review-results-card__body"
    >
      <div className="review-result-tabs" role="tablist" aria-label="复习结果视图">
        <button type="button" role="tab" aria-selected={view === "questions"} onClick={() => setView("questions")}>答题回顾</button>
        <button type="button" role="tab" aria-selected={view === "replay"} onClick={() => setView("replay")}>会话回放</button>
        <button type="button" role="tab" aria-selected={view === "discussions"} onClick={() => setView("discussions")}>深入讨论 <span>{discussionCount}</span></button>
        <button type="button" role="tab" aria-selected={view === "reports"} onClick={() => setView("reports")}>报告 <span>{round.reports.length}</span></button>
      </div>

      <div className="review-results-card__content">
        {view === "replay" ? (
          <div className="review-result-replay review-conversation--chat">
            <div className="review-chat-log" role="log" aria-label="复习会话回放">
              {!round.messages.length && round.attempts.length ? <p className="status-note">此历史轮次没有消息投影，以下内容由已保存的作答记录还原。</p> : null}
              {replayMessages.length ? replayMessages.map((message) => <ReviewChatMessage key={message.id} message={message} />) : <p className="status-note">本轮没有可回放的对话记录。</p>}
            </div>
          </div>
        ) : null}

        {view === "questions" ? (
          <div className="review-question-review">
            <aside className="review-question-review__index" aria-label="本轮题目列表">
              <div className="review-result-metrics">
                {([
                  { key: "completed", value: completed, label: "已完成" },
                  { key: "good", value: good, label: "掌握良好" },
                  { key: "skipped", value: skipped, label: "跳过" },
                ] as const).map((metric) => (
                  <button
                    type="button"
                    key={metric.key}
                    aria-pressed={filter === metric.key}
                    aria-label={`${metric.label} ${metric.value}，点击筛选`}
                    onClick={() => setFilter((current) => current === metric.key ? "all" : metric.key)}
                  >
                    <strong>{metric.value}</strong><span>{metric.label}</span>
                  </button>
                ))}
              </div>
              <div className="review-result-filter-meta">
                <span>{filter === "all" ? "全部题目" : `已筛选：${filter === "completed" ? "已完成" : filter === "good" ? "掌握良好" : "跳过"}`}</span>
                <strong>{visibleAttempts.length} 道</strong>
              </div>
              <div className="review-question-review__list">
                {visibleAttempts.map((attempt) => (
                  <button
                    type="button"
                    key={attempt.id}
                    aria-current={selectedAttempt?.id === attempt.id}
                    onClick={() => setSelectedOrdinal(attempt.ordinal)}
                  >
                    <span>{attempt.ordinal}</span>
                    <div><strong>{attempt.ordinal}. {attempt.questionSnapshot.title}</strong><small>{attemptResult(attempt)}</small></div>
                    {attempt.discussionSessionId ? <MessageCircle size={15} aria-label="已有深入讨论会话" /> : null}
                  </button>
                ))}
              </div>
            </aside>
            <section className="review-question-review__detail" aria-label="题目回顾详情">
              {selectedAttempt ? (
                <>
                  <header>
                    <div><span>第 {selectedAttempt.ordinal} 题 · {attemptResult(selectedAttempt)}</span><h3>{selectedAttempt.questionSnapshot.title}</h3></div>
                    {startDiscussion(selectedAttempt)}
                  </header>
                  <div className="review-question-review__detail-scroll">
                    <section><h4>题目</h4><p>{selectedAttempt.questionSnapshot.questionText}</p></section>
                    <section><h4>你的回答</h4><p>{selectedAttempt.skipped ? "本题已跳过" : selectedAttempt.answer || "未作答"}</p></section>
                    <section><h4>评估结论</h4>{selectedAttempt.evaluation ? <p>{selectedAttempt.evaluation.evidence}</p> : <p className="status-note">本题没有评价结果。</p>}</section>
                  </div>
                </>
              ) : <p className="status-note">当前筛选条件下没有题目。</p>}
            </section>
          </div>
        ) : null}

        {view === "discussions" ? (
          <section className="review-discussion-manager" aria-label="深入讨论会话管理">
            <header>
              <div><MessagesSquare size={20} /><div><h3>逐题深入讨论</h3><p>所有题目的讨论入口集中在这里，后续可随时回来继续。</p></div></div>
              <strong>{discussionCount} / {round.attempts.length} 已建立</strong>
            </header>
            <div className="review-discussion-manager__list">
              {round.attempts.map((attempt) => (
                <article key={attempt.id}>
                  <span>{attempt.ordinal}</span>
                  <div><h4>{attempt.questionSnapshot.title}</h4><p>{attemptResult(attempt)} · {attempt.discussionSessionId ? "已有讨论记录" : "尚未开始讨论"}</p></div>
                  {startDiscussion(attempt)}
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {view === "reports" ? (
          <section className="review-report-list" aria-label="复习报告列表">
            <header><div><FileCheck2 size={20} /><div><h3>本轮报告</h3><p>报告确认与掌握度更新分开保存，处理状态可在这里追踪。</p></div></div></header>
            {round.reports.map((report, index) => {
              const waitingForPrevious = round.reports
                .slice(0, index)
                .some((item) => !item.publication && item.status === "review_pending");
              const pendingState = report.id === activeApprovalReportId
                ? "当前待确认"
                : waitingForPrevious
                  ? "等待上一份确认"
                  : "正在准备确认";
              return (
              <article className="review-report-artifact" data-selected={selectedReportId === report.id || undefined} key={report.id}>
                <div>
                  <strong>{report.title}</strong>
                  <span>{report.publication
                    ? publicationText[report.publication.state] ?? "已确认"
                    : report.status === "rejected"
                      ? "已退回"
                      : activeReportIndex >= 0 && index < activeReportIndex
                        ? "已处理"
                        : pendingState}</span>
                </div>
                {report.publication ? (
                  <div>
                    <p>{report.reportKind === "mastery_report" ? "这份掌握度更新已经确认，可随时回看。" : "这份复习报告已经保存，可随时回看。"}</p>
                    {report.publication.state === "index_stale" ? <span role="alert">知识索引待重新扫描，报告正文仍可查看。</span> : null}
                    {onOpenApproval ? <Button size="sm" variant="secondary" onClick={() => onOpenApproval(report.id)}>查看报告</Button> : null}
                  </div>
                ) : report.status === "rejected" ? (
                  <div>
                    <p>这份报告已退回，草稿仍保留用于回看。</p>
                    {onOpenApproval ? <Button size="sm" variant="secondary" onClick={() => onOpenApproval(report.id)}>查看报告</Button> : null}
                  </div>
                ) : (
                  <div>
                    <p>{report.reportKind === "mastery_report" ? "确认后会更新后续复习使用的掌握度。" : "确认后会把本轮复习总结保存到知识库。"}</p>
                    {onOpenApproval ? <Button size="sm" variant={report.id === activeApprovalReportId ? "primary" : "secondary"} onClick={() => onOpenApproval(report.id)}>{report.id === activeApprovalReportId ? "去确认" : waitingForPrevious ? "查看确认顺序" : "查看确认进度"}</Button> : null}
                  </div>
                )}
              </article>
              );
            })}
            {!round.reports.length ? <p className="status-note">本轮暂无报告。</p> : null}
            {round.executionStatus === "waiting_for_approval" ? (
              <div className="review-report-approval-note">
                <div><strong>还有 {round.reports.filter((report) => !report.publication).length} 项需要确认</strong><p>先核对复习报告，再处理掌握度更新；确认内容在右侧显示。</p></div>
                {onOpenApproval ? <Button size="sm" onClick={() => onOpenApproval(activeApprovalReportId ?? undefined)}>去确认</Button> : null}
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </Card>
  );
}
