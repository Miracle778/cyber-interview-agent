import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Database, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { toActionableError } from "../../shared/api/errorAdvice";
import {
  confirmTraceCleanupPlan,
  createTraceCleanupPlan,
  getTraceRetentionPolicy,
  replaceTraceRetentionPolicy,
  type TraceCleanupPlanResource,
  type TraceRetentionPolicyResource,
} from "./settingsApi";


const OPTIONS: Array<{
  value: TraceRetentionPolicyResource["bodyPolicy"];
  title: string;
  description: string;
}> = [
  {
    value: "days",
    title: "保留 90 天",
    description: "默认。到期后删除正文，保留运行、事件、哈希和质量元数据。",
  },
  {
    value: "permanent",
    title: "永久保留正文",
    description: "完整 Trace 一直留在本地，占用空间会持续增长。",
  },
  {
    value: "metadata_only",
    title: "仅保留元数据",
    description: "下次清理会移除所有非活动运行的正文，之后不能查看 Prompt 或原始响应。",
  },
];

export function AgentTraceRetentionSettings({
  workspaceId,
}: {
  workspaceId: string;
}) {
  const client = useQueryClient();
  const [plan, setPlan] = useState<TraceCleanupPlanResource | null>(null);
  const [confirming, setConfirming] = useState(false);
  const policy = useQuery({
    queryKey: ["agent-trace-retention", workspaceId],
    queryFn: () => getTraceRetentionPolicy(workspaceId),
  });
  const update = useMutation({
    mutationFn: (value: TraceRetentionPolicyResource["bodyPolicy"]) =>
      replaceTraceRetentionPolicy(workspaceId, value),
    onSuccess: (resource) => {
      client.setQueryData(["agent-trace-retention", workspaceId], resource);
      setPlan(null);
    },
  });
  const preview = useMutation({
    mutationFn: () => createTraceCleanupPlan(workspaceId),
    onSuccess: setPlan,
  });
  const cleanup = useMutation({
    mutationFn: (cleanupId: string) =>
      confirmTraceCleanupPlan(workspaceId, cleanupId),
    onSuccess: (resource) => {
      setPlan(resource);
      setConfirming(false);
      void client.invalidateQueries({ queryKey: ["agent-observability"] });
    },
  });
  const error = policy.error ?? update.error ?? preview.error ?? cleanup.error;
  const actionable = error
    ? toActionableError(error, "Trace 保留设置处理失败")
    : null;
  const selected = policy.data?.bodyPolicy ?? "days";

  return (
    <div className="trace-retention-settings">
      <header>
        <span aria-hidden="true"><Database size={18} /></span>
        <div>
          <h4>Trace 正文保留</h4>
          <p>正文和可重建元数据分开管理；清理不会删除运行记录、事件类型或证据哈希。</p>
        </div>
      </header>
      <fieldset disabled={policy.isPending || update.isPending}>
        <legend className="sr-only">Trace 正文保留策略</legend>
        {OPTIONS.map((option) => (
          <label key={option.value}>
            <input
              type="radio"
              name="trace-retention"
              value={option.value}
              checked={selected === option.value}
              onChange={() => update.mutate(option.value)}
            />
            <span><strong>{option.title}</strong><small>{option.description}</small></span>
          </label>
        ))}
      </fieldset>
      <div className="trace-retention-settings__actions">
        <button type="button" disabled={preview.isPending} onClick={() => preview.mutate()}>
          {preview.isPending ? "正在计算…" : "预览清理"}
        </button>
        <small>预览只计算文件、事件和字节，不移动或删除任何内容。</small>
      </div>
      {plan ? (
        <section className="trace-cleanup-preview" aria-label="Trace 清理预览">
          <header><ShieldCheck size={17} /><strong>清理预览</strong><span>{plan.status}</span></header>
          <dl>
            <div><dt>文件</dt><dd>{plan.fileCount}</dd></div>
            <div><dt>事件正文</dt><dd>{plan.eventCount}</dd></div>
            <div><dt>空间</dt><dd>{formatBytes(plan.totalBytes)}</dd></div>
            <div><dt>受保护活动运行</dt><dd>{plan.protectedActiveRuns}</dd></div>
          </dl>
          {plan.status === "planned" && plan.fileCount > 0 ? (
            <button type="button" onClick={() => setConfirming(true)}>
              <Trash2 size={15} />确认清理
            </button>
          ) : null}
          {plan.status === "partial_failure" ? (
            <p role="alert">部分正文未能安全清理，已保留失败收据，可稍后重试。</p>
          ) : null}
          {plan.status === "completed" ? (
            <p role="status">正文已删除；运行、事件元数据和哈希仍可查询。</p>
          ) : null}
        </section>
      ) : null}
      {actionable ? (
        <p className="trace-retention-settings__error" role="alert">
          <AlertTriangle size={16} />{actionable.message}
        </p>
      ) : null}
      {confirming && plan ? (
        <div className="dialog-backdrop" role="presentation">
          <section className="trace-cleanup-dialog" role="dialog" aria-modal="true" aria-labelledby="trace-cleanup-title">
            <h3 id="trace-cleanup-title">确认删除 Trace 正文</h3>
            <p>将删除 {plan.fileCount} 个文件中的 {plan.eventCount} 条正文（{formatBytes(plan.totalBytes)}）。此操作不能从元数据索引恢复。</p>
            <p>活动运行已排除：{plan.protectedActiveRuns} 个。</p>
            <footer>
              <button type="button" onClick={() => setConfirming(false)}>取消</button>
              <button type="button" disabled={cleanup.isPending} onClick={() => cleanup.mutate(plan.id)}>
                {cleanup.isPending ? "正在清理…" : "确认删除正文"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}
