import type { ReactNode } from "react";
import { CheckCircle2, LoaderCircle, TriangleAlert } from "lucide-react";

interface AgentProcessCardProps {
  status: "running" | "completed" | "failed" | "stopped";
  title: string;
  summary?: string;
  children?: ReactNode;
}

export function AgentProcessCard({ status, title, summary, children }: AgentProcessCardProps) {
  const Icon = status === "running" ? LoaderCircle : status === "failed" ? TriangleAlert : CheckCircle2;
  const body = <div className="agent-process-card__body">{summary ? <p>{summary}</p> : null}{children}</div>;
  if (status === "running" || status === "failed") {
    return <section className={`agent-process-card is-${status}`} role={status === "running" ? "status" : "alert"}><header><Icon size={17} /><strong>{title}</strong></header>{body}</section>;
  }
  return <details className={`agent-process-card is-${status}`}><summary><Icon size={17} /><strong>{title}</strong></summary>{body}</details>;
}
