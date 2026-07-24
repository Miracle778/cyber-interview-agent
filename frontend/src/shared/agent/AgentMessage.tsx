import type { ReactNode } from "react";
import { Bot, Copy, UserRound } from "lucide-react";
import { MarkdownView } from "../../features/knowledge/MarkdownView";

function beijingTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

interface AgentMessageProps {
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
  pending?: boolean;
  children?: ReactNode;
}

export function AgentMessage({ role, content, createdAt, pending = false, children }: AgentMessageProps) {
  const user = role === "user";
  return (
    <article className={`agent-conversation-message agent-conversation-message--${role}`}>
      <span className="agent-conversation-message__avatar" aria-hidden="true">
        {user ? <UserRound size={17} /> : <Bot size={17} />}
      </span>
      <div className="agent-conversation-message__content">
        <header>
          <strong>{user ? "你" : "画像助手"}</strong>
          {pending ? <span>发送中</span> : null}
          {beijingTime(createdAt) ? <time dateTime={createdAt}>{beijingTime(createdAt)}</time> : null}
          <button
            type="button"
            aria-label="复制消息"
            title="复制"
            onClick={() => void navigator.clipboard?.writeText(content)}
          >
            <Copy size={14} />
          </button>
        </header>
        <div className="agent-conversation-message__bubble">
          {user ? <p>{content}</p> : <MarkdownView markdown={content} />}
          {children}
        </div>
      </div>
    </article>
  );
}
