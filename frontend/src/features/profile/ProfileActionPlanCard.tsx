import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, RefreshCw, ShieldAlert } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { cancelProfileActionPlan, confirmProfileActionPlan, getProfileActionPlan, retryProfileActionPlan } from "./profileApi";
import { userFacingPlanSummary } from "./profilePresentation";

const operationLabels: Record<string, string> = { propose_claim_create: "补充一条简历要点", propose_claim_update: "更新一条简历要点", propose_claim_reject: "移除一条简历要点", propose_material_derived_version: "生成简历新版本", set_publication_selection: "调整资料使用范围", request_reassessment: "重新分析简历" };
const fieldLabels: Record<string, string> = { name: "名称", title: "名称", role: "职责", company: "公司", organization: "组织", school: "学校", institution: "学校", degree: "学历", major: "专业", field: "专业", description: "具体内容", tech_stack: "使用技术", skills: "相关技能", sub_skills: "具体技能", proficiency: "熟练程度", period: "时间", start_date: "开始时间", end_date: "结束时间" };
const statusLabels: Record<string, string> = { pending: "待执行", completed: "已完成", failed: "未完成", skipped: "已跳过", conflict: "需要重新确认" };

function readableValue(value: Record<string, unknown>) {
  const rows = Object.entries(value).filter(([key]) => key !== "category" && key !== "confidence");
  return <dl className="profile-plan-value">{rows.map(([key, item]) => <div key={key}><dt>{fieldLabels[key] ?? key.replaceAll("_", " ")}</dt><dd>{Array.isArray(item) ? item.join("、") : item && typeof item === "object" ? Object.values(item).map(String).join("、") : String(item ?? "—")}</dd></div>)}</dl>;
}

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
    <header><ListChecks size={19} /><div><strong>建议的修改步骤</strong><small>{plan.items.length} 项 · 确认前不会修改简历信息</small></div></header>
    <p>{userFacingPlanSummary(plan.requestSummary)}</p>
    {plan.stale ? <div className="profile-plan-warning"><ShieldAlert size={16} />简历信息已经变化，请重新生成修改建议。</div> : null}
    <ol>{plan.items.map((item) => <li key={item.itemId}><strong>{operationLabels[item.operation] ?? item.operation}</strong><span>{statusLabels[item.status] ?? item.status}</span>{item.before ? <section><small>修改前</small>{readableValue(item.before)}</section> : null}<section><small>{item.before ? "修改后" : "建议内容"}</small>{readableValue(item.after)}</section>{item.evidenceIds.length ? <small>来自简历 {item.evidenceIds.length} 处</small> : null}</li>)}</ol>
    <footer>
      {plan.canConfirm ? <Button loading={confirm.isPending} disabled={busy} onClick={() => confirm.mutate()}>确认执行</Button> : null}
      {plan.canCancel ? <Button variant="secondary" loading={cancel.isPending} disabled={busy} onClick={() => cancel.mutate()}>取消方案</Button> : null}
      {plan.retryable ? <Button loading={retry.isPending} disabled={busy} onClick={() => retry.mutate()}><RefreshCw size={15} />重试失败项</Button> : null}
    </footer>
  </article>;
}
