import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AgentWorkspaceShell } from "../../shared/agent/AgentWorkspaceShell";
import { AgentMessage } from "../../shared/agent/AgentMessage";
import { AgentComposer, type AgentReasoningEffort } from "../../shared/agent/AgentComposer";
import { Button } from "../../shared/ui/Button";
import { elapsedSeconds } from "../../shared/time";
import { listProviders } from "../settings/settingsApi";
import { DeepDiveContextPanel } from "./DeepDiveContextPanel";
import { DeepDiveProcessCard } from "./DeepDiveProcessCard";
import type { DeepDiveResource } from "./jobTargetTypes";

export function DeepDiveWorkspace({ resource, busy = false, stopping = false, onSend, onStop, onControl, onRestart, onChooseProject, onRetry, onResolve, onDispatchGap, onOpenProfile }: { resource: DeepDiveResource; busy?: boolean; stopping?: boolean; onSend: (content: string, configuration: { providerModelId?: string; reasoningEffort: AgentReasoningEffort }) => void; onStop: (executionId: string) => void; onControl: (action: "pause" | "resume" | "terminate") => void; onRestart: () => void; onChooseProject: () => void; onRetry: (executionId: string) => void; onResolve: (messageId: string, resolution: "abandoned" | "replaced", replacement?: string) => void; onDispatchGap: (gap: DeepDiveResource["gaps"][number]) => void; onOpenProfile: () => void }) {
  const [asideOpen, setAsideOpen] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [modelId, setModelId] = useState(resource.runtime.providerModelId ?? "");
  const [reasoningEffort, setReasoningEffort] = useState<AgentReasoningEffort>(resource.runtime.reasoningEffort ?? "none");
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const models = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled ? provider.models.filter((model) => model.enabled).map((model) => ({ id: model.id, label: `${provider.name} / ${model.displayName}` })) : []), [providers.data]);
  const unresolved = [...resource.messages].reverse().find((item) => item.role === "user" && item.resolutionStatus === "unresolved");
  const recoveryExecution = unresolved ? [...resource.executions].reverse().find((item) => item.inputMessageId === unresolved.id) : undefined;
  const runningExecution = [...resource.executions].reverse().find((item) => item.status === "running");
  const running = Boolean(runningExecution);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const processingSeconds = (executionId: string | null) => {
    const execution = executionId ? resource.executions.find((item) => item.id === executionId) : null;
    if (!execution?.startedAt) return null;
    const end = execution.finishedAt ?? new Date(now).toISOString();
    return elapsedSeconds(execution.startedAt, end);
  };
  return <div className="deep-dive-workspace"><AgentWorkspaceShell
    asideOpen={asideOpen}
    onAsideOpenChange={setAsideOpen}
    asideLabel="本次依据"
    header={<div className="deep-dive-header"><div><span>当前项目</span><h2>{resource.projectTitle || "项目深挖"}</h2><p>围绕一个项目逐步梳理事实、表达和岗位追问。</p></div><div>{resource.status === "active" ? <Button variant="secondary" disabled={stopping} onClick={() => onControl("pause")}>暂停会话</Button> : resource.status === "paused" ? <Button variant="secondary" onClick={() => onControl("resume")}>继续会话</Button> : null}{!["completed", "terminated"].includes(resource.status) ? <Button variant="danger" disabled={running || stopping} onClick={() => { if (window.confirm("结束后将不能继续回答，确认结束本轮项目深挖吗？")) onControl("terminate"); }}>结束本轮</Button> : <><Button variant="secondary" onClick={onChooseProject}>选择其他项目</Button><Button onClick={onRestart}>重新开始本项目</Button></>}</div></div>}
    conversation={<div className="deep-dive-conversation"><div className="deep-dive-conversation__timeline">
      {resource.messages.filter((message) => message.resolutionStatus !== "replaced").map((message) => <AgentMessage key={message.id} role={message.role} content={message.content} createdAt={message.createdAt} processingSeconds={message.role === "assistant" ? processingSeconds(message.executionId) : null} assistantLabel="项目教练" />)}
      {runningExecution ? <DeepDiveProcessCard execution={runningExecution} elapsedSeconds={processingSeconds(runningExecution.id)} onRetry={() => undefined} onReplace={() => undefined} onAbandon={() => undefined} /> : null}
      {recoveryExecution && unresolved && !runningExecution ? <DeepDiveProcessCard recovery execution={recoveryExecution} onRetry={() => onRetry(recoveryExecution.id)} onReplace={() => { const replacement = window.prompt("修改这条回答后重试", unresolved.content); if (replacement?.trim()) onResolve(unresolved.id, "replaced", replacement); }} onAbandon={() => onResolve(unresolved.id, "abandoned")} /> : null}
    </div><AgentComposer busy={busy || running} disabled={Boolean(unresolved) || resource.status !== "active"} stopping={stopping} modelId={modelId} models={models} reasoningEffort={reasoningEffort} recipientLabel="项目教练" placeholder={resource.status === "completed" ? "本次项目深挖已完成" : resource.status === "paused" ? "继续会话后可以回答" : unresolved ? "请先处理上一次未完成的回答" : "回答当前问题，尽量说明你的具体行动和结果…"} onModelChange={setModelId} onReasoningEffortChange={setReasoningEffort} onSend={(content) => onSend(content, { providerModelId: modelId || undefined, reasoningEffort })} onStop={() => { if (runningExecution) onStop(runningExecution.id); }} /></div>}
    aside={<DeepDiveContextPanel resource={resource} onDispatchGap={onDispatchGap} onOpenProfile={onOpenProfile} />}
  /></div>;
}
