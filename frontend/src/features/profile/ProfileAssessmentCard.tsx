import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import { getProfileAssessment } from "./profileApi";

export function ProfileAssessmentCard({ workspaceId, assessmentId }: { workspaceId: string; assessmentId: string }) {
  const query = useQuery({ queryKey: ["profile-assessment", workspaceId, assessmentId], queryFn: ({ signal }) => getProfileAssessment(workspaceId, assessmentId, signal) });
  if (query.isLoading) return <article className="profile-agent-card" role="status">正在读取评估结果…</article>;
  if (!query.data) return <article className="profile-agent-card profile-agent-card--error" role="alert">评估结果暂时无法读取。</article>;
  const result = query.data.result;
  return <article className="profile-agent-card">
    <header><ClipboardCheck size={19} /><div><strong>画像评估</strong><small>{query.data.proposalIds.length} 条待确认建议</small></div></header>
    <p>{result.summary ?? "评估已完成"}</p>
    <div className="profile-assessment-grid">
      <section><strong>优势</strong><ul>{(result.strengths ?? []).map((item) => <li key={item}>{item}</li>)}</ul></section>
      <section><strong>待补强</strong><ul>{[...(result.gaps ?? []), ...(result.risks ?? [])].map((item) => <li key={item}>{item}</li>)}</ul></section>
    </div>
  </article>;
}
