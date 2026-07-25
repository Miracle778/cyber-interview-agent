import { useEffect, useRef, useState, type ReactNode } from "react";
import { Bot, Check, Copy, UserRound } from "lucide-react";
import { MarkdownView } from "../../features/knowledge/MarkdownView";
import { formatBeijingTime } from "../time";
import { formatElapsedSeconds } from "../time";

interface AgentMessageProps {
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
  pending?: boolean;
  children?: ReactNode;
  assistantLabel?: string;
  processingSeconds?: number | null;
}

export function AgentMessage({ role, content, createdAt, pending = false, children, assistantLabel = "画像助手", processingSeconds = null }: AgentMessageProps) {
  const user = role === "user";
  const displayTime = createdAt ? formatBeijingTime(createdAt, false) : null;
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const resetTimer = useRef<number | null>(null);
  useEffect(() => () => { if (resetTimer.current !== null) window.clearTimeout(resetTimer.current); }, []);
  async function copyMessage() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(content);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
    resetTimer.current = window.setTimeout(() => setCopyStatus("idle"), 1800);
  }
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
          {!user && processingSeconds !== null ? <span>· 耗时 {formatElapsedSeconds(processingSeconds)}</span> : null}
          <button
            type="button"
            aria-label={copyStatus === "copied" ? "已复制" : "复制消息"}
            title={copyStatus === "copied" ? "已复制" : "复制"}
            onClick={() => void copyMessage()}
          >
            {copyStatus === "copied" ? <Check size={14} /> : <Copy size={14} />}
          </button>
          {copyStatus !== "idle" ? <span className={`agent-conversation-message__copy-status agent-conversation-message__copy-status--${copyStatus}`} role="status">{copyStatus === "copied" ? "已复制" : "复制失败"}</span> : null}
        </header>
        <div className="agent-conversation-message__bubble">
          {user ? <p>{content}</p> : <MarkdownView markdown={content} />}
          {children}
        </div>
      </div>
    </article>
  );
}
