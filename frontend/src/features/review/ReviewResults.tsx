import { BarChart3, MessageCircle } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import type { ReviewRound } from "./reviewTypes";

export function ReviewResults({ round, onDiscuss }: { round: ReviewRound; onDiscuss: (ordinal: number) => void }) {
  const good = round.attempts.filter((item) => item.evaluation?.score === "good").length;
  return (
    <Card title="本轮复习结果" icon={<BarChart3 size={18} />}>
      <div className="review-result-metrics"><div><strong>{round.attempts.length}</strong><span>已完成</span></div><div><strong>{good}</strong><span>掌握良好</span></div><div><strong>{round.attempts.filter((item) => item.skipped).length}</strong><span>跳过</span></div></div>
      <div className="review-result-list">{round.attempts.map((attempt) => <article key={attempt.id}><div><strong>{attempt.ordinal}. {attempt.questionSnapshot.title}</strong><span>{attempt.skipped ? "已跳过" : attempt.evaluation?.score}</span></div>{attempt.evaluation ? <p>{attempt.evaluation.evidence}</p> : null}<Button size="sm" variant="ghost" onClick={() => onDiscuss(attempt.ordinal)}><MessageCircle size={14} />深入讨论</Button></article>)}</div>
      {round.reports.map((report) => <article className="review-report-artifact" key={report.id}><strong>{report.title}</strong><span>{report.status}</span>{report.publication ? <><span>发布状态：{report.publication.state}</span><code>{report.publication.target_path}</code>{report.publication.state === "index_stale" ? <span role="alert">索引待重新扫描</span> : null}</> : null}</article>)}
      {round.executionStatus === "waiting_for_approval" ? <p className="status-note">报告与掌握度草稿已生成，人工确认只会在右侧待确认区域出现。</p> : null}
    </Card>
  );
}
