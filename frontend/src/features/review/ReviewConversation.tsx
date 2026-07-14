import { AlertTriangle, Bot, Pause, RotateCcw, Send, SkipForward, StopCircle, UserRound } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound, ReviewTimelineMessage } from "./reviewTypes";

function TimelineMessage({ message }: { message: ReviewTimelineMessage }) {
  const user = message.role === "user";
  const evaluation = message.messageKind === "evaluation_card" ? message.payload.evaluation as { score?: string; evidence?: string; missing_key_points?: string[] } | undefined : undefined;
  return <article className={`review-chat-message review-chat-message--${user ? "user" : "agent"}`}><div><span>{user ? <UserRound size={15} /> : <Bot size={15} />}</span><strong>{user ? "你" : "复习 Agent"}</strong></div><p>{message.content}</p>{evaluation ? <section className="review-evaluation-card"><strong>评价：{evaluation.score ?? "完成"}</strong>{evaluation.evidence ? <p>{evaluation.evidence}</p> : null}{evaluation.missing_key_points?.length ? <small>待补充：{evaluation.missing_key_points.join("、")}</small> : null}</section> : null}</article>;
}

export function ReviewConversation({ round, optimisticMessage, busy, onSubmit, onSkip, onCancel, onRetry }: { round: ReviewRound; optimisticMessage: ReviewTimelineMessage | null; busy: boolean; onSubmit: (value: string) => Promise<unknown>; onSkip: () => void; onCancel: () => void; onRetry: () => void }) {
  const [answer, setAnswer] = useState("");
  const latestAttempt = round.attempts.at(-1);
  const evaluating = latestAttempt?.status === "evaluating";
  const failed = latestAttempt?.status === "evaluation_failed";
  const messages = round.messages.length > 0 ? round.messages : round.currentInput ? [{ id: round.currentInput.id, executionId: round.executionId, role: "assistant", content: round.currentInput.prompt, messageKind: "review_prompt", payload: {}, createdAt: round.currentInput.createdAt }] : [];
  async function submit() {
    const value = answer.trim();
    if (!value) return;
    await onSubmit(value);
    setAnswer("");
  }
  return <section className="review-conversation review-conversation--chat" aria-label="当前复习轮次">
    <header className="review-conversation__header"><div><span>第 {Math.min(round.currentIndex + 1, round.questionCount)} / {round.questionCount} 题</span><h3>{round.currentQuestion?.title ?? "复习报告"}</h3></div><div className="review-progress" aria-label="轮次进度"><span style={{ width: `${Math.round((round.currentIndex / round.questionCount) * 100)}%` }} /></div></header>
    <div className="review-chat-log" role="log" aria-label="复习对话" aria-live="polite">{messages.map((message) => <TimelineMessage key={message.id} message={message} />)}{optimisticMessage ? <article className="review-chat-message review-chat-message--user is-pending"><div><UserRound size={15} /><strong>你</strong><span>发送中…</span></div><p>{optimisticMessage.content}</p></article> : null}{evaluating ? <div className="review-evaluation-stage" role="status"><span className="status-pulse" />正在评价回答</div> : null}{failed ? <div className="review-evaluation-error"><AlertTriangle size={17} /><div><strong>评价暂时失败</strong><p>你的回答已经保存，无需重新输入。</p></div><Button variant="secondary" size="sm" onClick={onRetry}><RotateCcw size={15} />重试评价</Button></div> : null}</div>
    {round.currentInput ? <div className="review-chat-composer"><label htmlFor="review-answer">{round.currentInput.kind === "follow_up" ? "补充回答" : "你的回答"}</label><textarea id="review-answer" value={answer} disabled={busy} onChange={(event) => setAnswer(event.target.value)} placeholder="先给出结论，再说明依据和边界条件" /><div className="btn-row"><Button disabled={!answer.trim() || busy} loading={busy} onClick={() => void submit().catch(() => undefined)}><Send size={16} />发送回答</Button><Button variant="secondary" disabled={busy} onClick={onSkip}><SkipForward size={16} />跳过本题</Button></div></div> : null}
    <footer className="review-chat-actions"><Button variant="ghost" onClick={() => history.back()}><Pause size={16} />稍后继续</Button><Button variant="danger" disabled={busy} onClick={onCancel}><StopCircle size={16} />结束本轮</Button></footer>
  </section>;
}
