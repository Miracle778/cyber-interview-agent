import type { ReactNode } from "react";
import { Bot, Copy, UserRound } from "lucide-react";
import { MarkdownView } from "../../features/knowledge/MarkdownView";
import { formatBeijingTime } from "../time";

interface AgentMessageProps {
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
  pending?: boolean;
  children?: ReactNode;
  assistantLabel?: string;
}

export function AgentMessage({ role, content, createdAt, pending = false, children, assistantLabel = "画像助手" }: AgentMessageProps) {
  const user = role === "user";
  const displayTime = createdAt ? formatBeijingTime(createdAt, false) : null;
  return (
    <article className={`agent-conversation-message agent-conversation-message--${role}`}>
      <span className="agent-conversation-message__avatar" aria-hidden="true">
        {user ? <UserRound size={17} /> : <Bot size={17} />}
      </span>
      <div className="agent-conversation-message__content">
        <header>
          <strong>{user ? "你" : assistantLabel}</strong>
          {pending ? <span>发送中</span> : null}
          {displayTime ? <time dateTime={createdAt}>{displayTime}</time> : null}
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
