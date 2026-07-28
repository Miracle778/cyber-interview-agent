import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle } from "lucide-react";
import type { MaterialLifecycleStatus, MaterialProcessingStatus } from "./profileTypes";

const processingLabels: Record<string, string> = {
  uploaded: "等待文本提取",
  parsing: "正在提取文本",
  parsed: "正在处理隐私信息",
  extracting: "正在整理简历要点",
  ready: "简历处理完成",
  parse_failed: "文本提取失败",
  extraction_failed: "简历要点整理失败",
};

export function ProfileStatusBadge({ status, lifecycle, pendingCount }: { status?: MaterialProcessingStatus | string | null; lifecycle?: MaterialLifecycleStatus | string; pendingCount?: number | null }) {
  const failed = status?.endsWith("_failed");
  const ready = status === "ready";
  const archived = lifecycle === "archived";
  const active = Boolean(status && !failed && !ready);
  const Icon = failed ? AlertTriangle : ready ? CheckCircle2 : active ? LoaderCircle : Clock3;
  const label = archived
    ? "已归档"
    : ready && typeof pendingCount === "number" && pendingCount > 0
      ? `${pendingCount} 条简历要点待确认`
      : status
        ? processingLabels[status] ?? status
        : "等待上传";
  return <span className={`profile-status profile-status--${failed ? "failed" : ready ? "ready" : archived ? "archived" : "active"}`}><Icon size={14} aria-hidden="true" />{label}</span>;
}

export { processingLabels };
