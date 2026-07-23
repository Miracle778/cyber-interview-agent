import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle } from "lucide-react";
import type { MaterialLifecycleStatus, MaterialProcessingStatus } from "./profileTypes";

const processingLabels: Record<string, string> = {
  uploaded: "等待文本提取",
  parsing: "正在提取文本",
  parsed: "正在脱敏",
  extracting: "正在提取画像",
  ready: "等待审核",
  parse_failed: "文本提取失败",
  extraction_failed: "画像提取失败",
};

export function ProfileStatusBadge({ status, lifecycle }: { status?: MaterialProcessingStatus | string | null; lifecycle?: MaterialLifecycleStatus | string }) {
  const failed = status?.endsWith("_failed");
  const ready = status === "ready";
  const archived = lifecycle === "archived";
  const active = Boolean(status && !failed && !ready);
  const Icon = failed ? AlertTriangle : ready ? CheckCircle2 : active ? LoaderCircle : Clock3;
  const label = archived ? "已归档" : status ? processingLabels[status] ?? status : "等待上传";
  return <span className={`profile-status profile-status--${failed ? "failed" : ready ? "ready" : archived ? "archived" : "active"}`}><Icon size={14} aria-hidden="true" />{label}</span>;
}

export { processingLabels };
