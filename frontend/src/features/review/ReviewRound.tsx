import { AlertCircle, Pause, Send, SkipForward, StopCircle } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound as ReviewRoundValue } from "./reviewTypes";

export function ReviewRound({ round, onSubmit, onSkip, onCancel, busy }: { round: ReviewRoundValue; onSubmit: (value: string) => Promise<unknown>; onSkip: () => void; onCancel: () => void; busy: boolean }) {
  const [answer, setAnswer] = useState("");
  const inputKey = round.currentInput?.id ?? "none";
  const current = round.currentQuestion;
  return (
    <section className="review-conversation" aria-label="当前复习轮次" key={inputKey}>
      <header className="review-conversation__header"><div><span>第 {Math.min(round.currentIndex + 1, round.questionCount)} / {round.questionCount} 题</span><h3>{current?.title ?? "等待报告生成"}</h3></div><div className="review-progress" aria-label="轮次进度"><span style={{ width: `${Math.round((round.currentIndex / round.questionCount) * 100)}%` }} /></div></header>
      <div className="review-message review-message--agent"><small>{round.currentInput?.kind === "follow_up" ? "必要追问" : "Agent 出题"}</small><p>{round.currentInput?.prompt ?? current?.questionText}</p></div>
      {round.attempts.map((attempt) => <div key={attempt.id} className="review-attempt-summary"><strong>第 {attempt.ordinal} 题</strong><span>{attempt.skipped ? "已跳过" : attempt.evaluation?.score ?? "已回答"}</span></div>)}
      <label className="field"><span className="field__label">{round.currentInput?.kind === "follow_up" ? "补充回答" : "你的回答"}</span><textarea className="field__input field__input--area" value={answer} disabled={busy || !round.currentInput} onChange={(event) => setAnswer(event.target.value)} placeholder="先给出结论，再说明依据和边界条件" /></label>
      <div className="btn-row"><Button disabled={!answer.trim() || busy || !round.currentInput} loading={busy} onClick={() => void onSubmit(answer.trim()).then(() => setAnswer("")).catch(() => undefined)}><Send size={16} />发送回答</Button><Button variant="secondary" disabled={busy || !round.currentInput} onClick={onSkip}><SkipForward size={16} />跳过本题</Button><Button variant="ghost" disabled={busy} onClick={() => history.back()}><Pause size={16} />稍后继续</Button><Button variant="danger" disabled={busy} onClick={onCancel}><StopCircle size={16} />结束本轮</Button></div>
      {!round.currentInput ? <p className="status-note"><AlertCircle size={14} />正在恢复当前输入，请稍候…</p> : null}
    </section>
  );
}
