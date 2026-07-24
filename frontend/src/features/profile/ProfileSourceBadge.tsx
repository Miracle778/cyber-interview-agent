import { FileText, MessageSquareText, PencilLine, Sparkles } from "lucide-react";
import type { ProfileSourceSummary } from "./profileTypes";

const sourceIcons = {
  resume_extraction: FileText,
  user_input: PencilLine,
  conversation: MessageSquareText,
  agent_inference: Sparkles,
};

export function ProfileSourceBadge({ source }: { source: ProfileSourceSummary }) {
  const Icon = sourceIcons[source.sourceKind as keyof typeof sourceIcons] ?? FileText;
  return <span className="profile-source-badge" title={source.status === "source_deleted" ? "原资料已删除，这条信息由你保留" : undefined}>
    <Icon size={13} aria-hidden="true" />
    {source.label}
  </span>;
}
