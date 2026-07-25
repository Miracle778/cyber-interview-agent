import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, FolderLock } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { getUnifiedProfile } from "../profile/profileApi";
import {
  answerDeepDive, confirmDocumentVersion, controlAnalysis, controlDeepDive, createDeepDive,
  createDocumentVersion, createJobTarget, decideProjectQuestion, decideProjectQuestions, editProjectQuestion, decideRequirements, cancelDeepDive,
  getCurrentAnalysis, getCurrentDeepDive, getReadiness, listJobTargets, listRequirements,
  dispatchProjectGap, resolveDeepDiveMessage, restartDeepDive, retryDeepDive, setProjectPriorities, startAnalysis,
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
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const workspaceId = workspace?.id ?? "";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<JobTargetTab>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [jdOpen, setJdOpen] = useState(false);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const targetsQuery = useQuery({ queryKey: ["job-targets", workspaceId], queryFn: ({ signal }) => listJobTargets(workspaceId, signal), enabled: Boolean(workspace) });
  const targets = useMemo(() => targetsQuery.data ?? [], [targetsQuery.data]);
  const returnTargetId = searchParams.get("target");
  const returnProjectId = searchParams.get("project");
  const returnTab = searchParams.get("tab");
  const target = targets.find((item) => item.id === selectedId) ?? targets[0] ?? null;
  useEffect(() => { if (target && selectedId !== target.id) setSelectedId(target.id); }, [selectedId, target?.id]);
  useEffect(() => {
    if (returnTargetId && targets.some((item) => item.id === returnTargetId)) setSelectedId(returnTargetId);
    if (returnProjectId) setActiveProjectId(returnProjectId);
    if (returnTab === "deep-dive") { setProjectPickerOpen(false); setTab("deep-dive"); }
  }, [returnProjectId, returnTab, returnTargetId, targets]);
  const requirements = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "requirements"], queryFn: ({ signal }) => listRequirements(workspaceId, target!.id, signal), enabled: Boolean(target) });
  const analysis = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "analysis"], queryFn: ({ signal }) => getCurrentAnalysis(workspaceId, target!.id, signal), enabled: Boolean(target), refetchInterval: (query) => (query.state.data as { status?: string } | null)?.status === "running" ? 1200 : false });
  const readiness = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "readiness"], queryFn: ({ signal }) => getReadiness(workspaceId, target!.id, signal), enabled: Boolean(target) });
  const profile = useQuery({ queryKey: ["unified-profile", workspaceId], queryFn: ({ signal }) => getUnifiedProfile(workspaceId, signal), enabled: Boolean(workspace) });
  const projects = (profile.data?.projects ?? []).map((item) => ({ id: item.claimId, title: item.title, summary: item.subtitle ?? undefined }));
  useEffect(() => { if (!projectPickerOpen && !activeProjectId && projects[0]) setActiveProjectId(projects[0].id); }, [activeProjectId, projectPickerOpen, projects[0]?.id]);
  const dive = useQuery({ queryKey: ["job-targets", workspaceId, target?.id, "deep-dive", activeProjectId], queryFn: ({ signal }) => getCurrentDeepDive(workspaceId, target!.id, activeProjectId!, signal), enabled: Boolean(target && activeProjectId), refetchInterval: (query) => (query.state.data as DeepDiveResource | null)?.executions.some((item) => item.status === "running") ? 1000 : false });
  async function refresh() { await Promise.all([client.invalidateQueries({ queryKey: ["job-targets", workspaceId] }), client.invalidateQueries({ queryKey: ["job-targets", workspaceId, target?.id] })]); }
  useEffect(() => {
    if (!target || !analysis.data || analysis.data.status === "running" || analysis.data.status === "paused") return;
    void client.invalidateQueries({ queryKey: ["job-targets", workspaceId] });
  }, [analysis.data?.id, analysis.data?.status, client, target?.id, workspaceId]);
  const create = useMutation({ mutationFn: (values: { roleName: string; seniority: string; companyName: string }) => createJobTarget(workspaceId, values), onSuccess: async (value) => { setSelectedId(value.id); setCreateOpen(false); await refresh(); } });
  const createFromJd = useMutation({ mutationFn: async (body: string) => { const created = await createJobTarget(workspaceId, { roleName: "", seniority: "", companyName: "" }); const version = await createDocumentVersion(workspaceId, created.id, body); const confirmed = await confirmDocumentVersion(workspaceId, created, version.id); await startAnalysis(workspaceId, confirmed); return confirmed; }, onSuccess: async (value) => { setSelectedId(value.id); setCreateOpen(false); await refresh(); } });
  const jd = useMutation({ mutationFn: async (body: string) => { const version = await createDocumentVersion(workspaceId, target!.id, body); const confirmed = await confirmDocumentVersion(workspaceId, target!, version.id); await startAnalysis(workspaceId, confirmed); return confirmed; }, onSuccess: async () => { setJdOpen(false); await refresh(); } });
  const runAnalysis = useMutation({ mutationFn: () => startAnalysis(workspaceId, target!), onSuccess: refresh });
  const analysisControl = useMutation({ mutationFn: (action: "pause" | "resume" | "terminate") => controlAnalysis(workspaceId, target!.id, analysis.data!, action), onSuccess: refresh });
  const decisions = useMutation({ mutationFn: ({ ids, decision }: { ids: string[]; decision: "pending" | "confirmed" | "rejected" }) => decideRequirements(workspaceId, target!.id, ids.map((id) => { const item = requirements.data!.find((value) => value.id === id)!; return { requirementId: id, expectedVersion: item.version, decision }; })), onSuccess: refresh });
  const priorities = useMutation({ mutationFn: ({ core, supplementary }: { core: string; supplementary: string[] }) => setProjectPriorities(workspaceId, target!, core, supplementary), onSuccess: refresh });
  const startDive = useMutation({ mutationFn: (projectId: string) => createDeepDive(workspaceId, target!.id, projectId), onSuccess: (value) => { setActiveProjectId(value.projectClaimId); setProjectPickerOpen(false); setTab("deep-dive"); void refresh(); } });
  const send = useMutation({ mutationFn: ({ content, configuration }: { content: string; configuration: { providerModelId?: string; reasoningEffort: "none" | "low" | "medium" | "high" } }) => answerDeepDive(workspaceId, target!.id, dive.data!.id, content, configuration), onSuccess: refresh });
  const stopDive = useMutation({ mutationFn: (executionId: string) => cancelDeepDive(workspaceId, target!.id, dive.data!.id, executionId), onSuccess: refresh });
  const diveControl = useMutation({ mutationFn: (action: "pause" | "resume" | "terminate") => controlDeepDive(workspaceId, target!.id, dive.data!.id, dive.data!.version, action), onSuccess: refresh });
  const restart = useMutation({ mutationFn: () => restartDeepDive(workspaceId, target!.id, dive.data!.id, dive.data!.version), onSuccess: (value) => { setActiveProjectId(value.projectClaimId); setProjectPickerOpen(false); void refresh(); } });
  const retry = useMutation({ mutationFn: (executionId: string) => retryDeepDive(workspaceId, target!.id, dive.data!.id, executionId), onSuccess: refresh });
  const resolve = useMutation({ mutationFn: ({ messageId, resolution, replacement }: { messageId: string; resolution: "abandoned" | "replaced"; replacement?: string }) => resolveDeepDiveMessage(workspaceId, target!.id, dive.data!.id, messageId, resolution, replacement), onSuccess: refresh });
  const questionDecision = useMutation({ mutationFn: ({ id, decision }: { id: string; decision: "confirmed" | "ignored" | "duplicate" }) => decideProjectQuestion(workspaceId, target!.id, id, decision), onSuccess: refresh });
  const questionBatchDecision = useMutation({ mutationFn: ({ ids, decision }: { ids: string[]; decision: "confirmed" | "ignored" }) => decideProjectQuestions(workspaceId, target!.id, ids, decision), onSuccess: refresh });
  const questionEdit = useMutation({ mutationFn: ({ id, title, question }: { id: string; title: string; question: string }) => editProjectQuestion(workspaceId, target!.id, id, { title, question }), onSuccess: refresh });
  const gapDispatch = useMutation({ mutationFn: (gapId: string) => dispatchProjectGap(workspaceId, target!.id, gapId), onSuccess: refresh });
  if (!workspace) return <div className="job-target-missing"><FolderLock /><h1>求职目标</h1><p>请先初始化工作区。</p><Link to="/settings">前往设置</Link></div>;
  return <section className="job-target-page"><JobTargetList targets={targets} selectedId={target?.id} onSelect={(id) => { setSelectedId(id); setProjectPickerOpen(false); setTab("overview"); }} onCreate={() => setCreateOpen(true)} />
    <main>{target ? <JobTargetWorkspace target={target} analysis={analysis.data} tab={tab} onTab={setTab}>
      {tab === "overview" ? <JobTargetOverview target={target} readiness={readiness.data} analysis={analysis.data} onEditJd={() => setJdOpen(true)} onStartAnalysis={() => runAnalysis.mutate()} onControl={(action) => analysisControl.mutate(action)} onNavigate={setTab} /> : null}
      {tab === "requirements" ? <RequirementWorkbench requirements={requirements.data ?? []} busy={decisions.isPending} onDecide={(ids, decision) => decisions.mutate({ ids, decision })} /> : null}
      {tab === "deep-dive" ? projectPickerOpen || !dive.data ? <ProjectPriorityPanel projects={projects} busy={priorities.isPending || startDive.isPending} onSave={(core, supplementary) => priorities.mutate({ core, supplementary })} onStart={(projectId) => startDive.mutate(projectId)} /> : <DeepDiveWorkspace resource={dive.data} busy={send.isPending} stopping={stopDive.isPending || restart.isPending || gapDispatch.isPending} onSend={(content, configuration) => send.mutate({ content, configuration })} onStop={(executionId) => stopDive.mutate(executionId)} onControl={(action) => diveControl.mutate(action)} onRestart={() => restart.mutate()} onChooseProject={() => setProjectPickerOpen(true)} onRetry={(executionId) => retry.mutate(executionId)} onResolve={(messageId, resolution, replacement) => resolve.mutate({ messageId, resolution, replacement })} onDispatchGap={(gap) => gapDispatch.mutate(gap.id)} onOpenProfile={() => navigate("/profile", { state: { returnTo: `/targets?${new URLSearchParams({ tab: "deep-dive", target: target.id, project: activeProjectId ?? "" })}`, returnLabel: "返回项目深挖" } })} /> : null}
      {tab === "review" ? <ProjectQuestionCandidates projectTitle={dive.data?.projectTitle} candidates={dive.data?.questionCandidates ?? []} busy={questionDecision.isPending || questionBatchDecision.isPending || questionEdit.isPending} onDecide={(id, decision) => questionDecision.mutate({ id, decision })} onBatchDecide={(ids, decision) => questionBatchDecision.mutate({ ids, decision })} onEdit={(id, title, question) => questionEdit.mutate({ id, title, question })} /> : null}
    </JobTargetWorkspace> : <div className="job-target-empty"><BriefcaseBusiness /><h1>建立第一个求职目标</h1><p>粘贴岗位描述，系统会拆出明确要求，并结合个人画像安排项目准备和项目题训练。</p><Button onClick={() => setCreateOpen(true)}>新建求职目标</Button></div>}</main>
    {createOpen ? <TargetDialog busy={create.isPending || createFromJd.isPending} onClose={() => setCreateOpen(false)} onSubmitJd={(body) => createFromJd.mutate(body)} onSubmitManual={(values) => create.mutate(values)} /> : null}
    {jdOpen && target ? <JdDialog onClose={() => setJdOpen(false)} onSubmit={(body) => jd.mutate(body)} /> : null}
  </section>;
}

function TargetDialog({ busy, onClose, onSubmitJd, onSubmitManual }: { busy: boolean; onClose: () => void; onSubmitJd: (body: string) => void; onSubmitManual: (values: { companyName: string; roleName: string; seniority: string }) => void }) {
  const [mode, setMode] = useState<"jd" | "manual">("jd");
  return <div className="job-target-dialog" role="dialog" aria-modal="true" aria-labelledby="target-dialog-title"><form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); if (mode === "jd") onSubmitJd(String(data.get("body") ?? "")); else onSubmitManual({ companyName: String(data.get("companyName") ?? ""), roleName: String(data.get("roleName") ?? ""), seniority: String(data.get("seniority") ?? "") }); }}><h2 id="target-dialog-title">新建求职目标</h2><div className="job-target-dialog__modes"><button type="button" aria-current={mode === "jd" ? "page" : undefined} onClick={() => setMode("jd")}>粘贴 JD</button><button type="button" aria-current={mode === "manual" ? "page" : undefined} onClick={() => setMode("manual")}>没有 JD，手动创建</button></div>{mode === "jd" ? <><p>直接粘贴岗位描述。系统会识别公司、岗位、经验范围和具体要求，你只需要核对结果。</p><label>岗位描述<textarea name="body" rows={12} required autoFocus placeholder="粘贴完整 JD…" /></label></> : <><label>公司（可选）<input name="companyName" /></label><label>岗位名称<input name="roleName" required /></label><label>职级或经验范围<input name="seniority" required placeholder="例如：高级 / 5-8 年" /></label></>}<footer><Button type="button" variant="secondary" onClick={onClose}>取消</Button><Button type="submit" loading={busy}>{mode === "jd" ? "识别并创建" : "创建目标"}</Button></footer></form></div>;
}

function JdDialog({ onClose, onSubmit }: { onClose: () => void; onSubmit: (body: string) => void }) {
  return <div className="job-target-dialog" role="dialog" aria-modal="true" aria-labelledby="jd-dialog-title"><form onSubmit={(event) => { event.preventDefault(); onSubmit(String(new FormData(event.currentTarget).get("body") ?? "")); }}><h2 id="jd-dialog-title">添加岗位描述</h2><p>粘贴完整 JD 或你整理的岗位方向。原文会保留为一个不可变版本。</p><label>岗位内容<textarea name="body" rows={12} required /></label><footer><Button type="button" variant="secondary" onClick={onClose}>稍后添加</Button><Button type="submit">保存并用于分析</Button></footer></form></div>;
}
