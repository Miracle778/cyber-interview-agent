import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, FolderLock } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { getUnifiedProfile } from "../profile/profileApi";
import {
  answerDeepDive, confirmDocumentVersion, controlAnalysis, controlDeepDive, createDeepDive,
  createDocumentVersion, createJobTarget, decideProjectQuestion, decideRequirements,
  getCurrentAnalysis, getCurrentDeepDive, getReadiness, listJobTargets, listRequirements,
  resolveDeepDiveMessage, retryDeepDive, setProjectPriorities, startAnalysis,
} from "./jobTargetApi";
import type { DeepDiveResource, JobTarget } from "./jobTargetTypes";
import { JobTargetList } from "./JobTargetList";
import { JobTargetWorkspace, type JobTargetTab } from "./JobTargetWorkspace";
import { JobTargetOverview } from "./JobTargetOverview";
import { RequirementWorkbench } from "./RequirementWorkbench";
import { ProjectPriorityPanel } from "./ProjectPriorityPanel";
import { DeepDiveWorkspace } from "./DeepDiveWorkspace";
import { ProjectQuestionCandidates } from "./ProjectQuestionCandidates";
import "./jobTargets.css";

export function JobTargetPage({ workspace }: { workspace: WorkspaceConfig | null }) {
  const client = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<JobTargetTab>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [jdOpen, setJdOpen] = useState(false);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const targetsQuery = useQuery({ queryKey: ["job-targets", workspaceId], queryFn: ({ signal }) => listJobTargets(workspaceId, signal), enabled: Boolean(workspace) });
  const targets = useMemo(() => targetsQuery.data ?? [], [targetsQuery.data]);
  const target = targets.find((item) => item.id === selectedId) ?? targets[0] ?? null;
  useEffect(() => { if (target && selectedId !== target.id) setSelectedId(target.id); }, [selectedId, target?.id]);
  const requirements = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "requirements"], queryFn: ({ signal }) => listRequirements(workspaceId, target!.id, signal), enabled: Boolean(target) });
  const analysis = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "analysis"], queryFn: ({ signal }) => getCurrentAnalysis(workspaceId, target!.id, signal), enabled: Boolean(target), refetchInterval: (query) => (query.state.data as { status?: string } | null)?.status === "running" ? 1200 : false });
  const readiness = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "readiness"], queryFn: ({ signal }) => getReadiness(workspaceId, target!.id, signal), enabled: Boolean(target) });
  const profile = useQuery({ queryKey: ["unified-profile", workspaceId], queryFn: ({ signal }) => getUnifiedProfile(workspaceId, signal), enabled: Boolean(workspace) });
  const projects = (profile.data?.projects ?? []).map((item) => ({ id: item.claimId, title: item.title, summary: item.subtitle ?? undefined }));
  useEffect(() => { if (!activeProjectId && projects[0]) setActiveProjectId(projects[0].id); }, [activeProjectId, projects[0]?.id]);
  const dive = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "deep-dive", activeProjectId], queryFn: ({ signal }) => getCurrentDeepDive(workspaceId, target!.id, activeProjectId!, signal), enabled: Boolean(target && activeProjectId), refetchInterval: (query) => (query.state.data as DeepDiveResource | null)?.executions.some((item) => item.status === "running") ? 1000 : false });
  async function refresh() { await Promise.all([client.invalidateQueries({ queryKey: ["job-targets", workspaceId] }), client.invalidateQueries({ queryKey: ["job-targets", workspaceId, target?.id] })]); }
  const create = useMutation({ mutationFn: (values: { roleName: string; seniority: string; companyName: string }) => createJobTarget(workspaceId, values), onSuccess: async (value) => { setSelectedId(value.id); setCreateOpen(false); setJdOpen(true); await refresh(); } });
  const jd = useMutation({ mutationFn: async (body: string) => { const version = await createDocumentVersion(workspaceId, target!.id, body); const confirmed = await confirmDocumentVersion(workspaceId, target!, version.id); await startAnalysis(workspaceId, confirmed); return confirmed; }, onSuccess: async () => { setJdOpen(false); await refresh(); } });
  const runAnalysis = useMutation({ mutationFn: () => startAnalysis(workspaceId, target!), onSuccess: refresh });
  const analysisControl = useMutation({ mutationFn: (action: "pause" | "resume" | "terminate") => controlAnalysis(workspaceId, target!.id, analysis.data!, action), onSuccess: refresh });
  const decisions = useMutation({ mutationFn: ({ ids, decision }: { ids: string[]; decision: "confirmed" | "rejected" }) => decideRequirements(workspaceId, target!.id, ids.map((id) => { const item = requirements.data!.find((value) => value.id === id)!; return { requirementId: id, expectedVersion: item.version, decision }; })), onSuccess: refresh });
  const priorities = useMutation({ mutationFn: ({ core, supplementary }: { core: string; supplementary: string[] }) => setProjectPriorities(workspaceId, target!, core, supplementary), onSuccess: refresh });
  const startDive = useMutation({ mutationFn: (projectId: string) => createDeepDive(workspaceId, target!.id, projectId), onSuccess: (value) => { setActiveProjectId(value.projectClaimId); setTab("deep-dive"); void refresh(); } });
  const send = useMutation({ mutationFn: (content: string) => answerDeepDive(workspaceId, target!.id, dive.data!.id, content), onSuccess: refresh });
  const diveControl = useMutation({ mutationFn: (action: "pause" | "resume" | "terminate") => controlDeepDive(workspaceId, target!.id, dive.data!.id, dive.data!.version, action), onSuccess: refresh });
  const retry = useMutation({ mutationFn: (executionId: string) => retryDeepDive(workspaceId, target!.id, dive.data!.id, executionId), onSuccess: refresh });
  const resolve = useMutation({ mutationFn: ({ messageId, resolution, replacement }: { messageId: string; resolution: "abandoned" | "replaced"; replacement?: string }) => resolveDeepDiveMessage(workspaceId, target!.id, dive.data!.id, messageId, resolution, replacement), onSuccess: refresh });
  const questionDecision = useMutation({ mutationFn: ({ id, decision }: { id: string; decision: "confirmed" | "ignored" | "duplicate" }) => decideProjectQuestion(workspaceId, target!.id, id, decision), onSuccess: refresh });
  if (!workspace) return <div className="job-target-missing"><FolderLock /><h1>求职目标</h1><p>请先初始化工作区。</p><Link to="/settings">前往设置</Link></div>;
  return <section className="job-target-page"><JobTargetList targets={targets} selectedId={target?.id} onSelect={(id) => { setSelectedId(id); setTab("overview"); }} onCreate={() => setCreateOpen(true)} />
    <main>{target ? <JobTargetWorkspace target={target} tab={tab} onTab={setTab}>
      {tab === "overview" ? <JobTargetOverview target={target} readiness={readiness.data} analysis={analysis.data} onEditJd={() => setJdOpen(true)} onStartAnalysis={() => runAnalysis.mutate()} onControl={(action) => analysisControl.mutate(action)} /> : null}
      {tab === "requirements" ? <RequirementWorkbench requirements={requirements.data ?? []} busy={decisions.isPending} onDecide={(ids, decision) => decisions.mutate({ ids, decision })} /> : null}
      {tab === "deep-dive" ? dive.data ? <DeepDiveWorkspace resource={dive.data} busy={send.isPending} onSend={(content) => send.mutate(content)} onControl={(action) => diveControl.mutate(action)} onRetry={(executionId) => retry.mutate(executionId)} onResolve={(messageId, resolution, replacement) => resolve.mutate({ messageId, resolution, replacement })} /> : <ProjectPriorityPanel projects={projects} busy={priorities.isPending} onSave={(core, supplementary) => priorities.mutate({ core, supplementary })} onStart={(projectId) => startDive.mutate(projectId)} /> : null}
      {tab === "review" ? <ProjectQuestionCandidates candidates={dive.data?.questionCandidates ?? []} onDecide={(id, decision) => questionDecision.mutate({ id, decision })} /> : null}
    </JobTargetWorkspace> : <div className="job-target-empty"><BriefcaseBusiness /><h1>建立第一个求职目标</h1><p>粘贴岗位描述，系统会拆出明确要求，并结合个人画像安排项目准备和项目题训练。</p><Button onClick={() => setCreateOpen(true)}>新建求职目标</Button></div>}</main>
    {createOpen ? <TargetDialog title="新建求职目标" fields={["companyName", "roleName", "seniority"]} onClose={() => setCreateOpen(false)} onSubmit={(values) => create.mutate({ companyName: values.companyName, roleName: values.roleName, seniority: values.seniority })} /> : null}
    {jdOpen && target ? <JdDialog onClose={() => setJdOpen(false)} onSubmit={(body) => jd.mutate(body)} /> : null}
  </section>;
}

function TargetDialog({ title, fields, onClose, onSubmit }: { title: string; fields: string[]; onClose: () => void; onSubmit: (values: Record<string, string>) => void }) {
  return <div className="job-target-dialog" role="dialog" aria-modal="true" aria-labelledby="target-dialog-title"><form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); onSubmit(Object.fromEntries(fields.map((field) => [field, String(data.get(field) ?? "")]))); }}><h2 id="target-dialog-title">{title}</h2><label>公司（可选）<input name="companyName" /></label><label>岗位名称<input name="roleName" required /></label><label>职级或经验范围<input name="seniority" required placeholder="例如：高级 / 5-8 年" /></label><footer><Button type="button" variant="secondary" onClick={onClose}>取消</Button><Button type="submit">下一步</Button></footer></form></div>;
}

function JdDialog({ onClose, onSubmit }: { onClose: () => void; onSubmit: (body: string) => void }) {
  return <div className="job-target-dialog" role="dialog" aria-modal="true" aria-labelledby="jd-dialog-title"><form onSubmit={(event) => { event.preventDefault(); onSubmit(String(new FormData(event.currentTarget).get("body") ?? "")); }}><h2 id="jd-dialog-title">添加岗位描述</h2><p>粘贴完整 JD 或你整理的岗位方向。原文会保留为一个不可变版本。</p><label>岗位内容<textarea name="body" rows={12} required /></label><footer><Button type="button" variant="secondary" onClick={onClose}>稍后添加</Button><Button type="submit">保存并用于分析</Button></footer></form></div>;
}
