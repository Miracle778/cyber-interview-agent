import { FormEvent, useEffect, useRef, useState } from "react";
import { Bot, Send, Square, UserRound } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { AgentEvent, AgentMessage, StreamingAssistantState } from "../agent/agentTypes";
import { ProfileActionPlanCard } from "./ProfileActionPlanCard";
import { ProfileAssessmentCard } from "./ProfileAssessmentCard";
import { ProfileToolStage } from "./ProfileToolStage";

export function ProfileConversation({ workspaceId, messages, events, streaming, executionStatus, busy, stopping, onSend, onStop, onChanged }: { workspaceId: string; messages: AgentMessage[]; events: AgentEvent[]; streaming: StreamingAssistantState | null; executionStatus?: string; busy: boolean; stopping: boolean; onSend: (message: string) => void; onStop: () => void; onChanged: () => void }) {
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
    <div ref={logRef} className="profile-agent-log" role="log" aria-live="polite" aria-label="画像 Agent 对话">
      {!messages.length ? <div className="profile-agent-empty"><Bot size={28} /><h3>从当前画像开始讨论</h3><p>可以询问证据、评估优势与风险，或提出明确的画像修改需求。</p></div> : null}
      {messages.map((message) => <ProfileMessage key={message.id} workspaceId={workspaceId} message={message} onChanged={onChanged} />)}
      {toolEvents.map((event) => <ProfileToolStage key={event.id} event={event} executionActive={executionActive} />)}
      {streaming?.text ? <div className="profile-agent-message profile-agent-message--assistant"><Bot size={18} /><p>{streaming.text}</p></div> : null}
    </div>
    <form className="profile-agent-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor="profile-agent-message">发送给画像 Agent</label>
      <textarea ref={composerRef} id="profile-agent-message" rows={2} value={text} disabled={busy} placeholder="询问画像，或描述需要评估、修改的内容…" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
      <div><small>Shift+Enter 换行</small>{busy ? <Button type="button" variant="danger" disabled={stopping} onClick={onStop}><Square size={15} />{stopping ? "正在停止…" : "停止"}</Button> : <Button type="submit" disabled={!text.trim()} aria-label="发送"><Send size={17} />发送</Button>}</div>
    </form>
  </main>;
}

function ProfileMessage({ workspaceId, message, onChanged }: { workspaceId: string; message: AgentMessage; onChanged: () => void }) {
  const resourceId = typeof message.payload?.resourceId === "string" ? message.payload.resourceId : null;
  if (message.messageKind === "assessment_card" && resourceId) return <ProfileAssessmentCard workspaceId={workspaceId} assessmentId={resourceId} />;
  if (message.messageKind === "action_plan_card" && resourceId) return <ProfileActionPlanCard workspaceId={workspaceId} planId={resourceId} onChanged={onChanged} />;
  const user = message.role === "user";
  const Icon = user ? UserRound : Bot;
  return <div className={`profile-agent-message profile-agent-message--${user ? "user" : "assistant"}`}><Icon size={18} aria-hidden="true" /><p>{message.content}</p></div>;
}
