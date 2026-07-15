import { Bot, UserRound } from "lucide-react";
import type { CurationMessage } from "./reviewTypes";
import { SourceFileCard } from "./SourceFileCard";

function cardLabel(message: CurationMessage): string | null {
  if (message.messageKind !== "question_card") return null;
  const label = message.payload.filename ?? message.payload.title;
  return typeof label === "string" && label.trim() ? label.trim() : "题目详情";
}

function formatMessageTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function elapsedLabel(startedAt: string | null | undefined, createdAt: string) {
  if (!startedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = new Date(createdAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  const seconds = Math.round((end - start) / 1000);
  return seconds < 60 ? `耗时 ${seconds} 秒` : `耗时 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function SessionMessage({ message, pending = false, startedAt = null }: { message: CurationMessage; pending?: boolean; startedAt?: string | null }) {
  const fromUser = message.role === "user";
  const detailLabel = cardLabel(message);
  const time = formatMessageTime(message.createdAt);
  const elapsed = message.messageKind === "curation_summary" || message.messageKind === "command_receipt" ? elapsedLabel(startedAt, message.createdAt) : null;
  return (
    <article className={`review-chat-message review-chat-message--${fromUser ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
      <span className="review-chat-message__avatar" aria-hidden="true">{fromUser ? <UserRound size={17} /> : <Bot size={17} />}</span>
      <div className="review-chat-message__content"><div className="review-chat-message__meta"><strong>{fromUser ? "你" : "题匠"}</strong>{time ? <span className="review-chat-message__timing"><time dateTime={message.createdAt}>{time}</time>{elapsed ? <span>· {elapsed}</span> : null}</span> : null}{pending ? <span>发送中…</span> : null}</div><div className="review-chat-message__bubble">{detailLabel ? <SourceFileCard filename={detailLabel} content={message.content} /> : <p>{message.content}</p>}</div></div>
    </article>
  );
}
