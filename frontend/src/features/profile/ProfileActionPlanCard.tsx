import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, RefreshCw, ShieldAlert } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { cancelProfileActionPlan, confirmProfileActionPlan, getProfileActionPlan, retryProfileActionPlan } from "./profileApi";

const operationLabels: Record<string, string> = { propose_claim_create: "新增画像建议", propose_claim_update: "更新画像建议", propose_claim_reject: "拒绝画像事实", propose_material_derived_version: "生成简历新版本", set_publication_selection: "调整发布范围", request_reassessment: "重新评估画像" };

export function ProfileActionPlanCard({ workspaceId, planId, onChanged }: { workspaceId: string; planId: string; onChanged?: () => void }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["profile-action-plan", workspaceId, planId], queryFn: ({ signal }) => getProfileActionPlan(workspaceId, planId, signal) });
  const refresh = async () => { await client.invalidateQueries({ queryKey: ["profile-action-plan", workspaceId, planId] }); onChanged?.(); };
  const confirm = useMutation({ mutationFn: () => confirmProfileActionPlan(workspaceId, query.data!), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => cancelProfileActionPlan(workspaceId, query.data!), onSuccess: refresh });
  const retry = useMutation({ mutationFn: () => retryProfileActionPlan(workspaceId, planId), onSuccess: refresh });
  if (query.isLoading) return <article className="profile-agent-card" role="status">正在读取修改方案…</article>;
  const plan = query.data;
  if (!plan) return <article className="profile-agent-card profile-agent-card--error" role="alert">修改方案暂时无法读取。</article>;
  const busy = confirm.isPending || cancel.isPending || retry.isPending;
  return <article className="profile-agent-card profile-action-plan-card">
    <header><ListChecks size={19} /><div><strong>画像修改方案</strong><small>{plan.items.length} 项 · {plan.status}</small></div></header>
    <p>{plan.requestSummary}</p>
    {plan.stale ? <div className="profile-plan-warning"><ShieldAlert size={16} />画像已经变化，请重新生成方案。</div> : null}
    <ol>{plan.items.map((item) => <li key={item.itemId}><strong>{operationLabels[item.operation] ?? item.operation}</strong><span>{item.status}</span>{item.before ? <pre>修改前 {JSON.stringify(item.before, null, 2)}</pre> : null}<pre>修改后 {JSON.stringify(item.after, null, 2)}</pre>{item.evidenceIds.length ? <small>证据 {item.evidenceIds.length} 条</small> : null}</li>)}</ol>
    <footer>
      {plan.canConfirm ? <Button loading={confirm.isPending} disabled={busy} onClick={() => confirm.mutate()}>确认执行</Button> : null}
      {plan.canCancel ? <Button variant="secondary" loading={cancel.isPending} disabled={busy} onClick={() => cancel.mutate()}>取消方案</Button> : null}
      {plan.retryable ? <Button loading={retry.isPending} disabled={busy} onClick={() => retry.mutate()}><RefreshCw size={15} />重试失败项</Button> : null}
    </footer>
  </article>;
}
