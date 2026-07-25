import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, LoaderCircle, RotateCcw, Square, WandSparkles } from "lucide-react";
import { formatElapsedSeconds, parseApiTimestamp } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import type { ProfileMaterialVersionDetail } from "./profileTypes";

const activeStatuses = new Set(["uploaded", "parsing", "parsed", "extracting"]);

function elapsedLabel(startedAt: string | null | undefined, now: number) {
  if (!startedAt) return "刚刚开始";
  const started = parseApiTimestamp(startedAt).getTime();
  if (!Number.isFinite(started)) return "正在处理";
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  return formatElapsedSeconds(seconds);
}

export function ProfileBackgroundTask({
  detail,
  stopping,
  continuing,
  onOpen,
  onStop,
  onContinue,
  onOpenPending,
}: {
  detail: ProfileMaterialVersionDetail | null;
  stopping: boolean;
  continuing: boolean;
  onOpen: () => void;
  onStop: () => void;
  onContinue: () => void;
  onOpenPending: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const active = Boolean(detail && activeStatuses.has(detail.processingStatus));
  const failed = detail?.processingStatus === "parse_failed" || detail?.processingStatus === "extraction_failed";
  const completedWithSuggestions = detail?.processingStatus === "ready" && detail.proposalCounts.pending > 0;

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, detail?.id]);

  const stage = useMemo(() => detail?.stages.find((item) => item.status === "active" || item.status === "failed"), [detail?.stages]);
  if (!detail || (!active && !failed && !completedWithSuggestions)) return null;

  if (completedWithSuggestions) {
    return <section className="profile-background-task profile-background-task--completed" role="status">
      <CheckCircle2 size={19} aria-hidden="true" />
      <div><strong>画像建议已生成</strong><span>已整理出 {detail.proposalCounts.pending} 条待确认信息。</span></div>
      <Button size="sm" onClick={onOpenPending}>确认这 {detail.proposalCounts.pending} 条<ArrowRight size={15} /></Button>
    </section>;
  }

  if (failed) {
    return <section className="profile-background-task profile-background-task--failed" role="status">
      <RotateCcw size={19} aria-hidden="true" />
      <div><strong>{detail.processingStatus === "parse_failed" ? "文本提取没有完成" : "画像建议没有整理完成"}</strong><span>已完成的文件和文本处理均已保留。</span></div>
      <Button size="sm" variant="secondary" loading={continuing} onClick={onContinue}>继续整理</Button>
      <Button size="sm" variant="ghost" onClick={onOpen}>查看详情</Button>
    </section>;
  }

  return <section className="profile-background-task" role="status" aria-live="polite">
    <LoaderCircle className="profile-background-task__spinner" size={19} aria-hidden="true" />
    <div>
      <strong>{stage?.label ?? "正在处理简历"}</strong>
      <span>已识别 {detail.evidencePage.total} 个内容区块 · <Clock3 size={13} />已运行 {elapsedLabel(detail.execution?.startedAt ?? detail.createdAt, now)}</span>
    </div>
    <Button size="sm" variant="ghost" onClick={onOpen}><WandSparkles size={15} />查看过程</Button>
    {detail.execution?.status === "running" || detail.execution?.status === "cancelling"
      ? <Button size="sm" variant="danger" loading={stopping} onClick={onStop}><Square size={14} />停止整理</Button>
      : null}
  </section>;
}
