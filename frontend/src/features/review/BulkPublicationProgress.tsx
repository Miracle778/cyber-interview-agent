import { AlertCircle, CheckCircle2, ChevronDown, LoaderCircle, RotateCcw, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { elapsedSeconds, formatElapsedSeconds } from "../../shared/time";
import type { BulkPublication, QuestionCandidate } from "./reviewTypes";

const activeStatuses = new Set(["accepted", "running"]);
const retryableStatuses = new Set(["partial_failure", "failed", "cancelled", "interrupted"]);

function elapsedLabel(startedAt: string, completedAt: string | null, now: number) {
  const seconds = elapsedSeconds(startedAt, completedAt ?? new Date(now).toISOString());
  return seconds === null ? "" : formatElapsedSeconds(seconds);
}

const statusText: Record<string, string> = {
  accepted: "准备发布",
  running: "正在发布",
  completed: "发布完成",
  partial_failure: "部分未完成",
  failed: "发布失败",
  cancelled: "已停止",
  interrupted: "发布中断",
};

function publicationFailureReason(errorCode: string | null) {
  const messages: Record<string, string> = {
    publication_failed: "写入题库时失败，题目仍保留，可以重试发布。",
    database_locked: "题库当时正忙，题目仍保留，可以稍后重试。",
    publication_conflict: "题目状态已发生变化，请刷新后再处理。",
    publication_index_failed: "题目已保存，但搜索索引更新失败。",
  };
  return errorCode ? messages[errorCode] ?? "本题没有发布成功，题目仍保留，可以重试。" : "本题没有发布成功，题目仍保留，可以重试。";
}

export function BulkPublicationProgress({
  operation,
  candidates,
  stopping,
  retrying,
  onStop,
  onRetry,
  onOpenCandidate = () => undefined,
}: {
  operation: BulkPublication;
  candidates: Record<string, QuestionCandidate>;
  stopping: boolean;
  retrying: boolean;
  onStop: () => void;
  onRetry: () => void;
  onOpenCandidate?: (candidateId: string) => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const [failedOnly, setFailedOnly] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const active = activeStatuses.has(operation.status);
  useEffect(() => {
    if (!active) return;
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, [active]);

  const counts = useMemo(() => operation.items.reduce((result, item) => {
    result[item.status] = (result[item.status] ?? 0) + 1;
    return result;
  }, {} as Record<string, number>), [operation.items]);
  const completed = counts.completed ?? 0;
  const failed = counts.failed ?? 0;
  const processed = completed + failed;
  const total = operation.items.length;
  const current = operation.items.find((item) => item.status === "running");
  const currentTitle = current ? candidates[current.candidateId]?.question.title ?? current.candidateId : null;
  const retryable = retryableStatuses.has(operation.status) && operation.items.some((item) => item.status !== "completed");
  const visibleItems = failedOnly ? operation.items.filter((item) => item.status === "failed") : operation.items;
  useEffect(() => {
    if (failed === 0) setFailedOnly(false);
  }, [failed]);

  return (
    <section className={`bulk-publication-progress bulk-publication-progress--${operation.status}`} aria-label="一键发布进度">
      <header>
        <div>
          {active ? <LoaderCircle className="bulk-publication-progress__spinner" size={18} /> : retryableStatuses.has(operation.status) ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          <span><strong>{statusText[operation.status] ?? "发布状态"}</strong><small>已处理 {processed} / {total} · 已入库 {completed}{failed ? ` · 失败 ${failed}` : ""}</small></span>
        </div>
        <time>{elapsedLabel(operation.createdAt, operation.completedAt, now)}</time>
      </header>
      <div className="bulk-publication-progress__bar" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={processed}>
        <span style={{ width: `${total ? (processed / total) * 100 : 0}%` }} />
      </div>
      {currentTitle ? <p>当前正在发布：<strong>{currentTitle}</strong></p> : null}
      {failed > 0 ? <div className="bulk-publication-progress__failure-shortcut"><button type="button" aria-pressed={failedOnly} onClick={() => { setFailedOnly((currentValue) => !currentValue); setDetailsOpen(true); }}>只看失败 {failed}</button><span>失败题目没有丢失，可查看原因后重试。</span></div> : null}
      <div className="bulk-publication-progress__actions">
        <details open={detailsOpen} onToggle={(event) => setDetailsOpen(event.currentTarget.open)}>
          <summary>{failedOnly ? "失败题目" : "查看每道题的状态"} <ChevronDown size={15} /></summary>
          <ul>{visibleItems.map((item) => {
            const title = candidates[item.candidateId]?.question.title ?? item.candidateId;
            return <li key={item.id} className={item.status === "failed" ? "is-failed" : ""}>
              {item.status === "failed"
                ? <button type="button" aria-label={`查看失败题目：${title}`} onClick={() => onOpenCandidate(item.candidateId)}><span>{title}</span><small>{publicationFailureReason(item.errorCode)}</small></button>
                : <span>{title}</span>}
              <em className={`is-${item.status}`}>{item.status === "completed" ? "已入库" : item.status === "running" ? "发布中" : item.status === "failed" ? "失败" : "等待"}</em>
            </li>;
          })}</ul>
        </details>
        {active ? <Button size="sm" variant="danger" loading={stopping} onClick={onStop}><Square size={13} />停止发布</Button> : null}
        {retryable ? <Button size="sm" loading={retrying} onClick={onRetry}><RotateCcw size={14} />重试未完成项</Button> : null}
      </div>
    </section>
  );
}
