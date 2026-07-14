import { Bot, UserRound } from "lucide-react";
import type { CurationMessage } from "./reviewTypes";

export function SessionMessage({ message, pending = false }: { message: CurationMessage; pending?: boolean }) {
  const fromUser = message.role === "user";
  return (
    <article className={`curation-message curation-message--${fromUser ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
      <div className="curation-message__meta">
        {fromUser ? <UserRound size={15} /> : <Bot size={15} />}
        <strong>{fromUser ? "你" : "整理 Agent"}</strong>
        {pending ? <span>发送中…</span> : null}
      </div>
      <p>{message.content}</p>
    </article>
  );
}
