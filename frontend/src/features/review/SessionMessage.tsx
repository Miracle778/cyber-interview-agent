import { Bot, UserRound } from "lucide-react";
import type { CurationMessage } from "./reviewTypes";
import { SourceFileCard } from "./SourceFileCard";

function cardLabel(message: CurationMessage): string | null {
  if (message.messageKind !== "question_card") return null;
  const label = message.payload.filename ?? message.payload.title;
  return typeof label === "string" && label.trim() ? label.trim() : "题目详情";
}

export function SessionMessage({ message, pending = false }: { message: CurationMessage; pending?: boolean }) {
  const fromUser = message.role === "user";
  const detailLabel = cardLabel(message);
  return (
    <article className={`curation-message curation-message--${fromUser ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
      <div className="curation-message__meta">
        {fromUser ? <UserRound size={15} /> : <Bot size={15} />}
        <strong>{fromUser ? "你" : "题匠"}</strong>
        {pending ? <span>发送中…</span> : null}
      </div>
      {detailLabel ? (
        <SourceFileCard filename={detailLabel} content={message.content} />
      ) : (
        <p>{message.content}</p>
      )}
    </article>
  );
}
