import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getAgentSession, startAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { Button } from "../../shared/ui/Button";
import { ReviewChatMessage } from "./ReviewConversation";
import type { ReviewTimelineMessage } from "./reviewTypes";

export function ReviewDiscussion({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const session = useQuery({ queryKey: ["agent-session", sessionId], queryFn: () => getAgentSession(sessionId) });
  const stream = useAgentEvents(sessionId);
  const send = useMutation({
    mutationFn: (value: string) => startAgentExecution(sessionId, { message: value }),
    onSuccess: () => { setMessage(""); void client.invalidateQueries({ queryKey: ["agent-session", sessionId] }); },
  });
  useEffect(() => { if (stream.events.length) void client.invalidateQueries({ queryKey: ["agent-session", sessionId] }); }, [stream.events.length, sessionId]);
  const durable: ReviewTimelineMessage[] = (session.data?.messages ?? []).filter((item) => ["user", "assistant"].includes(item.role)).map((item) => ({ ...item, messageKind: "discussion", payload: {} }));
  const executionId = session.data?.latestExecution?.id ?? session.data?.latestExecutionId;
  const streamed = executionId ? stream.streamingByExecution[executionId] : undefined;
  const hasDurableResponse = durable.some((item) => item.executionId === executionId && item.role === "assistant");
  const streamingMessage: ReviewTimelineMessage | null = streamed?.text && !hasDurableResponse ? { id: `stream-${executionId}`, executionId: executionId ?? null, role: "assistant", content: streamed.text, messageKind: "discussion", payload: {}, createdAt: new Date().toISOString() } : null;
  const running = send.isPending || session.data?.latestExecution?.status === "running" || streamed?.status === "running";
  useEffect(() => { const log = logRef.current; if (log) log.scrollTop = log.scrollHeight; }, [durable.length, streamingMessage?.content]);

  async function submit() {
    const value = message.trim();
    if (!value || running) return;
    await send.mutateAsync(value);
  }

  return <section className="review-discussion review-conversation--chat" aria-label="深入讨论会话">
    <header className="review-discussion__header"><Button variant="ghost" size="sm" onClick={onClose}><ArrowLeft size={16} />返回复习报告</Button><div><span>围绕单题继续追问</span><h2>{session.data?.title ?? "深入讨论"}</h2></div></header>
    <div ref={logRef} className="review-chat-log" role="log" aria-label="深入讨论记录" aria-live="polite">{durable.map((item) => <ReviewChatMessage key={item.id} message={item} />)}{streamingMessage ? <ReviewChatMessage message={streamingMessage} pending={streamed?.status === "running"} /> : null}{running && !streamingMessage ? <div className="review-typing-row" role="status"><span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span><div className="review-typing-indicator"><span className="status-pulse" />复习助手正在整理思路…</div></div> : null}</div>
    <footer className="review-chat-composer"><label htmlFor="review-discussion-message">继续追问</label><div className="review-chat-composer__field"><textarea id="review-discussion-message" value={message} disabled={running} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit().catch(() => undefined); } }} placeholder="追问遗漏点、要求举例，或换一种方式解释…" /><div className="review-chat-composer__actions"><small>Enter 发送 · Shift+Enter 换行</small><Button disabled={!message.trim() || running} loading={running} onClick={() => void submit().catch(() => undefined)}><Send size={16} />发送</Button></div></div></footer>
  </section>;
}
