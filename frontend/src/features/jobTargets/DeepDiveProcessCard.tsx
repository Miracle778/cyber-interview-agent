import { AgentProcessCard } from "../../shared/agent/AgentProcessCard";
import type { DeepDiveExecution } from "./jobTargetTypes";

export function DeepDiveProcessCard({ execution, onRetry, onReplace, onAbandon }: { execution: DeepDiveExecution; onRetry: () => void; onReplace: () => void; onAbandon: () => void }) {
  const status = execution.status === "running" ? "running" : execution.status === "completed" ? "completed" : execution.status === "failed" ? "failed" : "stopped";
  return <AgentProcessCard status={status} title={status === "failed" ? "本次处理未完成" : status === "running" ? "正在整理你的回答" : "本次回答已处理"} summary={execution.errorMessage ?? undefined}>
    {status === "failed" ? <div className="deep-dive-recovery"><button type="button" onClick={onRetry}>按原内容重试</button><button type="button" onClick={onReplace}>修改后重试</button><button type="button" onClick={onAbandon}>放弃并继续</button></div> : null}
  </AgentProcessCard>;
}
