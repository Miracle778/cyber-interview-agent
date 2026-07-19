import { AlertTriangle, Bot, RotateCcw, Send, SkipForward, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound, ReviewTimelineMessage } from "./reviewTypes";
import { formatBeijingTime } from "../../shared/time";

function formatMessageTime(value: string) {
  return formatBeijingTime(value, false);
}

export function ReviewChatMessage({ message, pending = false }: { message: ReviewTimelineMessage; pending?: boolean }) {
  const user = message.role === "user";
  const evaluation = message.messageKind === "evaluation_card" ? message.payload.evaluation as { score?: string; evidence?: string; missing_key_points?: string[] } | undefined : undefined;
  const score = evaluation?.score === "good" ? "掌握良好" : evaluation?.score === "partial" ? "部分掌握" : evaluation?.score === "poor" ? "需要补充" : "评价完成";
  const time = formatMessageTime(message.createdAt);
  const showContent = !evaluation || message.content.trim() !== evaluation.evidence?.trim();
  return <article className={`review-chat-message review-chat-message--${user ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
    <span className="review-chat-message__avatar" aria-hidden="true">{user ? <UserRound size={17} /> : <Bot size={17} />}</span>
    <div className="review-chat-message__content">
      <div className="review-chat-message__meta"><strong>{user ? "你" : "复习助手"}</strong>{time ? <time dateTime={message.createdAt}>{time}</time> : null}{pending ? <span>发送中…</span> : null}</div>
      <div className="review-chat-message__bubble">
        {showContent ? user ? <p>{message.content}</p> : <div className="review-chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div> : null}
        {evaluation ? <section className="review-evaluation-card"><strong>{score}</strong>{evaluation.evidence ? <p>{evaluation.evidence}</p> : null}{evaluation.missing_key_points?.length ? <details><summary>查看 {evaluation.missing_key_points.length} 个待补充关键点</summary><ol>{evaluation.missing_key_points.map((point) => <li key={point}>{point}</li>)}</ol></details> : null}</section> : null}
      </div>
    </div>
  </article>;
}

export function ReviewConversation({ round, optimisticMessage, busy, onSubmit, onSkip, onRetry }: { round: ReviewRound; optimisticMessage: ReviewTimelineMessage | null; busy: boolean; onSubmit: (value: string) => Promise<unknown>; onSkip: () => void; onCancel?: () => void; onRetry: () => void }) {
  const [answer, setAnswer] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const latestAttempt = round.attempts.at(-1);
  const evaluating = latestAttempt?.status === "evaluating";
  const failed = latestAttempt?.status === "evaluation_failed";
  const messages = round.messages.length > 0 ? round.messages : round.currentInput ? [{ id: round.currentInput.id, executionId: round.executionId, role: "assistant", content: round.currentInput.prompt, messageKind: "review_prompt", payload: {}, createdAt: round.currentInput.createdAt }] : [];
  useEffect(() => {
    const log = logRef.current;
    if (!log) return;
    const scrollToLatest = () => { log.scrollTop = log.scrollHeight; };
    scrollToLatest();
    const frame = globalThis.requestAnimationFrame?.(scrollToLatest);
    return () => { if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame); };
  }, [round.id, messages.length, optimisticMessage?.id, evaluating, failed]);
  async function submit() {
    const value = answer.trim();
    if (!value) return;
    await onSubmit(value);
    setAnswer("");
  }
  return <section className="review-conversation review-conversation--chat" aria-label="当前复习轮次">
    <h2 className="review-conversation__sr-title">{round.currentQuestion?.title ?? "当前复习轮次"}</h2>
    <div ref={logRef} className="review-chat-log" role="log" aria-label="复习对话" aria-live="polite">{messages.map((message) => <ReviewChatMessage key={message.id} message={message} />)}{optimisticMessage ? <ReviewChatMessage message={optimisticMessage} pending /> : null}{evaluating ? <div className="review-typing-row" role="status"><span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span><div className="review-typing-indicator"><span className="status-pulse" />复习助手正在评价回答…</div></div> : null}{failed ? <div className="review-evaluation-error"><AlertTriangle size={17} /><div><strong>评价暂时失败</strong><p>你的回答已经保存，无需重新输入。</p></div><Button variant="secondary" size="sm" onClick={onRetry}><RotateCcw size={15} />重试评价</Button></div> : null}</div>
    {round.currentInput ? <footer className="review-chat-composer"><label htmlFor="review-answer">{round.currentInput.kind === "follow_up" ? "补充回答" : "你的回答"}</label><div className="review-chat-composer__field"><textarea id="review-answer" value={answer} disabled={busy} onChange={(event) => setAnswer(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit().catch(() => undefined); } }} placeholder="输入回答…" /><div className="review-chat-composer__actions"><small>Enter 发送 · Shift+Enter 换行</small><Button variant="ghost" disabled={busy} onClick={onSkip}><SkipForward size={16} />跳过</Button><Button disabled={!answer.trim() || busy} loading={busy} onClick={() => void submit().catch(() => undefined)}><Send size={16} />发送</Button></div></div></footer> : null}
  </section>;
}
