import { useState } from "react";
import { AgentWorkspaceShell } from "../../shared/agent/AgentWorkspaceShell";
import { AgentMessage } from "../../shared/agent/AgentMessage";
import { AgentComposer } from "../../shared/agent/AgentComposer";
import { Button } from "../../shared/ui/Button";
import { DeepDiveContextPanel } from "./DeepDiveContextPanel";
import { DeepDiveProcessCard } from "./DeepDiveProcessCard";
import type { DeepDiveResource } from "./jobTargetTypes";

export function DeepDiveWorkspace({ resource, busy = false, onSend, onControl, onRetry, onResolve }: { resource: DeepDiveResource; busy?: boolean; onSend: (content: string) => void; onControl: (action: "pause" | "resume" | "terminate") => void; onRetry: (executionId: string) => void; onResolve: (messageId: string, resolution: "abandoned" | "replaced", replacement?: string) => void }) {
  const [asideOpen, setAsideOpen] = useState(true);
  const failed = [...resource.executions].reverse().find((item) => item.status === "failed");
  const unresolved = resource.messages.find((item) => item.role === "user" && item.resolutionStatus === "unresolved");
  const running = resource.executions.some((item) => item.status === "running");
  return <div className="deep-dive-workspace"><AgentWorkspaceShell
    asideOpen={asideOpen}
    onAsideOpenChange={setAsideOpen}
    asideLabel="本次依据"
    header={<div className="deep-dive-header"><div><h2>项目深挖</h2><p>围绕一个项目逐步梳理事实、表达和岗位追问。</p></div><div>{resource.status === "active" ? <Button variant="secondary" onClick={() => onControl("pause")}>暂停</Button> : resource.status === "paused" ? <Button variant="secondary" onClick={() => onControl("resume")}>继续</Button> : null}<Button variant="danger" onClick={() => onControl("terminate")}>结束</Button></div></div>}
    conversation={<div className="deep-dive-conversation"><div className="deep-dive-conversation__timeline">
      {resource.messages.filter((message) => message.resolutionStatus !== "replaced").map((message) => <AgentMessage key={message.id} role={message.role} content={message.content} createdAt={message.createdAt} assistantLabel="项目教练" />)}
      {failed && unresolved ? <DeepDiveProcessCard execution={failed} onRetry={() => onRetry(failed.id)} onReplace={() => { const replacement = window.prompt("修改这条回答后重试", unresolved.content); if (replacement?.trim()) onResolve(unresolved.id, "replaced", replacement); }} onAbandon={() => onResolve(unresolved.id, "abandoned")} /> : null}
    </div><AgentComposer busy={busy || running || Boolean(unresolved)} stopping={false} modelId="" models={[]} reasoningEffort="none" placeholder={unresolved ? "请先处理上一次未完成的回答" : "回答当前问题，尽量说明你的具体行动和结果…"} onModelChange={() => undefined} onReasoningEffortChange={() => undefined} onSend={onSend} onStop={() => onControl("pause")} /></div>}
    aside={<DeepDiveContextPanel resource={resource} />}
  /></div>;
}
