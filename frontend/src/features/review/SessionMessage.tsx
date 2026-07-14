import { Bot, UserRound } from "lucide-react";
import type { CurationMessage } from "./reviewTypes";
import { SourceFileCard } from "./SourceFileCard";

const LONG_LINES = 6;
const LONG_CHARS = 280;

function extractFileLabel(content: string): { filename: string; body: string } | null {
  const newlineIdx = content.indexOf("\n");
  if (newlineIdx < 0) return null;
  const header = content.slice(0, newlineIdx);
  const colonIdx = header.indexOf(":");
  if (colonIdx < 0) return null;
  const filename = header.slice(colonIdx + 1).trim();
  const body = content.slice(newlineIdx + 1).trim();
  if (!filename || !body) return null;
  return { filename, body };
}

export function SessionMessage({ message, pending = false }: { message: CurationMessage; pending?: boolean }) {
  const fromUser = message.role === "user";
  const fileMatch = !fromUser ? extractFileLabel(message.content) : null;
  const isLong = !fromUser && !fileMatch && (message.content.length > LONG_CHARS || message.content.split("\n").length > LONG_LINES);
  return (
    <article className={`curation-message curation-message--${fromUser ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
      <div className="curation-message__meta">
        {fromUser ? <UserRound size={15} /> : <Bot size={15} />}
        <strong>{fromUser ? "你" : "题匠"}</strong>
        {pending ? <span>发送中…</span> : null}
      </div>
      {fileMatch ? (
        <SourceFileCard filename={fileMatch.filename} content={fileMatch.body} />
      ) : isLong ? (
        <SourceFileCard filename="完整内容" content={message.content} />
      ) : (
        <p>{message.content}</p>
      )}
    </article>
  );
}
