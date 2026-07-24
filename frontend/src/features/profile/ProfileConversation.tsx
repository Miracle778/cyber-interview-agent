import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowRight, Bot, ClipboardCheck } from "lucide-react";
import { AgentComposer, type AgentReasoningEffort } from "../../shared/agent/AgentComposer";
import { AgentMessage as SharedAgentMessage } from "../../shared/agent/AgentMessage";
import { AgentProcessCard } from "../../shared/agent/AgentProcessCard";
import type { AgentEvent, AgentMessage, StreamingAssistantState } from "../agent/agentTypes";
import { ProfileActionPlanCard } from "./ProfileActionPlanCard";
import { ProfileAssessmentCard } from "./ProfileAssessmentCard";
import { ProfileToolStage } from "./ProfileToolStage";
import { userFacingProfileAnswer } from "./profilePresentation";

const starterPrompts = [
  "检查简历信息是否完整",
  "找出表述不清或相互冲突的内容",
  "整理我的后端开发经历",
  "根据已确认资料生成自我介绍",
];

interface ProfileConversationProps {
  workspaceId: string;
  messages: AgentMessage[];
  events: AgentEvent[];
  streaming: StreamingAssistantState | null;
  executionStatus?: string;
  streamAnswer?: boolean;
  busy: boolean;
  stopping: boolean;
  models: { id: string; label: string }[];
  modelId: string;
  reasoningEffort: AgentReasoningEffort;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (effort: AgentReasoningEffort) => void;
  onSend: (message: string) => void;
  onStop: () => void;
  onChanged: () => void;
  onOpenPending?: () => void;
}

export function ProfileConversation({
  workspaceId,
  messages,
  events,
  streaming,
  executionStatus,
  streamAnswer = true,
  busy,
  stopping,
  models,
  modelId,
  reasoningEffort,
  onModelChange,
  onReasoningEffortChange,
  onSend,
  onStop,
  onChanged,
  onOpenPending,
}: ProfileConversationProps) {
  const [promptToFill, setPromptToFill] = useState<string | null>(null);
  const [following, setFollowing] = useState(true);
  const logRef = useRef<HTMLDivElement>(null);
  const scrollToBottom = useCallback(() => {
    const log = logRef.current;
    if (!log) return;
    log.scrollTop = log.scrollHeight;
    setFollowing(true);
  }, []);
  useEffect(() => {
    if (following) scrollToBottom();
  }, [events.length, following, messages.length, scrollToBottom, streaming?.text]);
  const toolEvents = useMemo(() => [...events.reduce((latestByCall, event) => {
    const payload = event.payload as Record<string, unknown>;
    const toolCallId = typeof payload.toolCallId === "string" ? payload.toolCallId : String(event.id);
    latestByCall.set(toolCallId, event);
    return latestByCall;
  }, new Map<string, AgentEvent>()).values()].slice(-8), [events]);
  const executionActive = ["running", "cancelling"].includes(executionStatus ?? "");
  const processStatus = executionActive ? "running" : executionStatus === "failed" ? "failed" : executionStatus === "cancelled" || executionStatus === "interrupted" ? "stopped" : "completed";
  return (
    <main className="agent-conversation">
      <div
        ref={logRef}
        className="agent-conversation__log"
        role="log"
        aria-live="polite"
        aria-label="画像助手对话"
        onScroll={(event) => {
          const target = event.currentTarget;
          setFollowing(target.scrollHeight - target.scrollTop - target.clientHeight < 72);
        }}
      >
        {!messages.length ? (
          <div className="agent-conversation__empty">
            <span><Bot size={26} /></span>
            <h3>想先了解什么？</h3>
            <p>画像助手只会使用你已经确认过的信息；任何修改仍需要你单独确认。</p>
            <div className="agent-conversation__starters">
              {starterPrompts.map((prompt) => <button key={prompt} type="button" disabled={busy} onClick={() => setPromptToFill(prompt)}>{prompt}</button>)}
            </div>
          </div>
        ) : null}
        {messages.map((message) => (
          <ProfileMessage
            key={message.id}
            workspaceId={workspaceId}
            message={message}
            onChanged={onChanged}
            onOpenPending={onOpenPending}
          />
        ))}
        {toolEvents.length ? (
          <AgentProcessCard
            status={processStatus}
            title={executionActive ? "正在查找并整理相关资料" : processStatus === "failed" ? "本次处理没有完成" : processStatus === "stopped" ? "本次处理已停止" : "资料处理过程"}
            summary={executionActive ? "你可以继续浏览历史消息，处理完成后结果会显示在下方。" : undefined}
          >
            {toolEvents.map((event) => <ProfileToolStage key={event.id} event={event} executionActive={executionActive} />)}
          </AgentProcessCard>
        ) : null}
        {executionActive && streamAnswer && streaming?.text ? <SharedAgentMessage role="assistant" content={streaming.text} pending /> : null}
        {executionActive && !streamAnswer ? <SharedAgentMessage role="assistant" content="正在整理可确认的结果…" pending /> : null}
      </div>
      {!following ? <button className="agent-conversation__new-message" type="button" onClick={scrollToBottom}><ArrowDown size={15} />有新回复，回到底部</button> : null}
      <AgentComposer
        busy={busy}
        stopping={stopping}
        modelId={modelId}
        models={models}
        reasoningEffort={reasoningEffort}
        placeholder="例如：检查我的项目经历是否缺少职责、方案或结果"
        promptToFill={promptToFill}
        onPromptFilled={() => setPromptToFill(null)}
        onModelChange={onModelChange}
        onReasoningEffortChange={onReasoningEffortChange}
        onSend={onSend}
        onStop={onStop}
      />
    </main>
  );
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
  return <SharedAgentMessage role={user ? "user" : "assistant"} content={user ? message.content : userFacingProfileAnswer(message.content)} createdAt={message.createdAt} />;
}
