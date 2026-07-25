import { AgentProcessCard } from "../../shared/agent/AgentProcessCard";
import type { DeepDiveExecution } from "./jobTargetTypes";

export function DeepDiveProcessCard({ execution, elapsedSeconds, recovery = false, onRetry, onReplace, onAbandon }: { execution: DeepDiveExecution; elapsedSeconds?: number | null; recovery?: boolean; onRetry: () => void; onReplace: () => void; onAbandon: () => void }) {
  const status = execution.status === "running" ? "running" : execution.status === "completed" ? "completed" : execution.status === "failed" || recovery ? "failed" : "stopped";
  return <AgentProcessCard status={status} title={status === "failed" ? "上一次回答未完成" : status === "running" ? `正在整理你的回答${elapsedSeconds !== null && elapsedSeconds !== undefined ? ` · ${elapsedSeconds} 秒` : ""}` : "本次回答已处理"} summary={execution.errorMessage ?? (recovery ? "暂停或停止时没有完成，可以继续处理原回答。" : undefined)}>
    {status === "failed" ? <div className="deep-dive-recovery"><button type="button" onClick={onRetry}>按原内容重试</button><button type="button" onClick={onReplace}>修改后重试</button><button type="button" onClick={onAbandon}>放弃并继续</button></div> : null}
  </AgentProcessCard>;
}
