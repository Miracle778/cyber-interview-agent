import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, ClipboardCheck, Send, Square, UserRound } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { AgentEvent, AgentMessage, StreamingAssistantState } from "../agent/agentTypes";
import { ProfileActionPlanCard } from "./ProfileActionPlanCard";
import { ProfileAssessmentCard } from "./ProfileAssessmentCard";
import { ProfileToolStage } from "./ProfileToolStage";
import { userFacingProfileAnswer } from "./profilePresentation";

export function ProfileConversation({ workspaceId, messages, events, streaming, executionStatus, streamAnswer = true, busy, stopping, onSend, onStop, onChanged, onOpenPending }: { workspaceId: string; messages: AgentMessage[]; events: AgentEvent[]; streaming: StreamingAssistantState | null; executionStatus?: string; streamAnswer?: boolean; busy: boolean; stopping: boolean; onSend: (message: string) => void; onStop: () => void; onChanged: () => void; onOpenPending?: () => void }) {
  const [text, setText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const wasBusy = useRef(busy);
  useEffect(() => { const log = logRef.current; if (log) log.scrollTop = log.scrollHeight; }, [messages.length, streaming?.text, events.length]);
  useEffect(() => { if (wasBusy.current && !busy) composerRef.current?.focus(); wasBusy.current = busy; }, [busy]);
  function submit(event: FormEvent) { event.preventDefault(); const value = text.trim(); if (!value || busy) return; setText(""); onSend(value); }
  const toolEvents = [...events.reduce((latestByCall, event) => {
    const payload = event.payload as Record<string, unknown>;
    const toolCallId = typeof payload.toolCallId === "string"
      ? payload.toolCallId
      : String(event.id);
    latestByCall.set(toolCallId, event);
    return latestByCall;
  }, new Map<string, AgentEvent>()).values()].slice(-6);
  const executionActive = ["running", "cancelling"].includes(executionStatus ?? "");
  return <main className="profile-agent-conversation">
    <div ref={logRef} className="profile-agent-log" role="log" aria-live="polite" aria-label="画像助手对话">
      {!messages.length ? <div className="profile-agent-empty"><Bot size={28} /><h3>想先了解什么？</h3><p>画像助手只会使用你已经确认过的信息；任何修改仍需要你单独确认。</p><div className="profile-agent-starters">
        {["检查简历信息是否完整", "找出表述不清或相互冲突的内容", "整理我的后端开发经历", "根据已确认资料生成自我介绍"].map((prompt) => <button key={prompt} type="button" disabled={busy} onClick={() => onSend(prompt)}>{prompt}</button>)}
      </div></div> : null}
      {messages.map((message) => <ProfileMessage key={message.id} workspaceId={workspaceId} message={message} onChanged={onChanged} onOpenPending={onOpenPending} />)}
      {toolEvents.map((event) => <ProfileToolStage key={event.id} event={event} executionActive={executionActive} />)}
      {executionActive && streamAnswer && streaming?.text ? <div className="profile-agent-message profile-agent-message--assistant"><Bot size={18} /><p>{streaming.text}</p></div> : null}
      {executionActive && !streamAnswer ? <div className="profile-agent-message profile-agent-message--assistant" role="status"><Bot size={18} /><p>正在整理可确认的结果…</p></div> : null}
    </div>
    <form className="profile-agent-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor="profile-agent-message">发送给画像助手</label>
      <textarea ref={composerRef} id="profile-agent-message" rows={2} value={text} disabled={busy} placeholder="例如：检查我的项目经历是否缺少职责、方案或结果" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
      <div><small>Shift+Enter 换行</small>{busy ? <Button type="button" variant="danger" disabled={stopping} onClick={onStop}><Square size={15} />{stopping ? "正在停止…" : "停止"}</Button> : <Button type="submit" disabled={!text.trim()} aria-label="发送"><Send size={17} />发送</Button>}</div>
    </form>
  </main>;
}

function ProfileMessage({ workspaceId, message, onChanged, onOpenPending }: { workspaceId: string; message: AgentMessage; onChanged: () => void; onOpenPending?: () => void }) {
  const resourceId = typeof message.payload?.resourceId === "string" ? message.payload.resourceId : null;
  if (message.messageKind === "assessment_card" && resourceId) return <ProfileAssessmentCard workspaceId={workspaceId} assessmentId={resourceId} />;
  if (message.messageKind === "action_plan_card" && resourceId) return <ProfileActionPlanCard workspaceId={workspaceId} planId={resourceId} onChanged={onChanged} />;
  if (message.messageKind === "proposal_card") {
    const count = typeof message.payload?.count === "number" ? message.payload.count : 0;
    return <section className="profile-conversation-proposal">
      <span><ClipboardCheck size={20} /></span>
      <div><strong>{count ? `${count} 条画像更新建议` : "画像更新建议"}</strong><p>这些内容还没有加入个人画像，需要你确认。</p></div>
      {onOpenPending ? <button type="button" onClick={onOpenPending}>去确认<ArrowRight size={15} /></button> : null}
    </section>;
  }
  const user = message.role === "user";
  const Icon = user ? UserRound : Bot;
  return <div className={`profile-agent-message profile-agent-message--${user ? "user" : "assistant"}`}><Icon size={18} aria-hidden="true" /><p>{user ? message.content : userFacingProfileAnswer(message.content)}</p></div>;
}
