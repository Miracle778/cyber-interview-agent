import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, MessageSquareText, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import { ApiError } from "../../shared/api/client";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { createJobTarget, listJobTargets } from "../jobTargets/jobTargetApi";
import { CleanupWorkbench } from "./CleanupWorkbench";
import { RetrospectiveCreateFlow, type RetrospectiveCreateValues } from "./RetrospectiveCreateFlow";
import { RetrospectiveList } from "./RetrospectiveList";
import {
  addSourceVersion,
  confirmCleanup,
  createRetrospective,
  getCleanup,
  getCurrentCleanup,
  listRetrospectives,
  resumeCleanup,
  startCleanup,
  stopCleanup,
  updateSegments,
} from "./retrospectiveApi";
import type { RetrospectiveLifecycle, SegmentEdit } from "./retrospectiveTypes";
import "./interviewRetrospectives.css";

const TABS: Array<{ value: RetrospectiveLifecycle; label: string; icon: typeof Archive }> = [
  { value: "active", label: "进行中", icon: MessageSquareText },
  { value: "archived", label: "已归档", icon: Archive },
  { value: "recycled", label: "回收站", icon: Trash2 },
];

export function InterviewRetrospectivePage({ workspace }: { workspace: WorkspaceConfig | null }) {
  const workspaceId = workspace?.id ?? "";
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lifecycle = (searchParams.get("lifecycle") as RetrospectiveLifecycle | null) ?? "active";
  const targetId = searchParams.get("jobTargetId") ?? "";
  const selectedId = searchParams.get("retrospectiveId");
  const cleanupId = searchParams.get("cleanupId");

  const targetsQuery = useQuery({
    queryKey: ["job-targets", workspaceId],
    queryFn: ({ signal }) => listJobTargets(workspaceId, signal),
    enabled: Boolean(workspaceId),
  });
  const listQuery = useQuery({
    queryKey: ["retrospectives", workspaceId, lifecycle, targetId],
    queryFn: ({ signal }) => listRetrospectives(workspaceId, { lifecycle, jobTargetId: targetId || undefined }, signal),
    enabled: Boolean(workspaceId),
  });
  const selected = useMemo(() => listQuery.data?.find((item) => item.id === selectedId) ?? listQuery.data?.[0] ?? null, [listQuery.data, selectedId]);
  const currentCleanupQuery = useQuery({
    queryKey: ["cleanup-current", workspaceId, selected?.id],
    queryFn: ({ signal }) => getCurrentCleanup(workspaceId, selected!.id, signal),
    enabled: Boolean(workspaceId && selected && !cleanupId && !selected.activeCleanupVersionId),
  });
  const effectiveCleanupId = cleanupId ?? selected?.activeCleanupVersionId ?? currentCleanupQuery.data?.id ?? null;
  const cleanupQuery = useQuery({
    queryKey: ["cleanup", workspaceId, selected?.id, effectiveCleanupId],
    queryFn: ({ signal }) => getCleanup(workspaceId, selected!.id, effectiveCleanupId!, signal),
    enabled: Boolean(workspaceId && selected && effectiveCleanupId),
    refetchInterval: (query) => ["queued", "running", "stopping"].includes(query.state.data?.status ?? "") ? 1_000 : false,
  });

  function patchSearch(patch: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setSearchParams(next);
  }

  const createFlow = useMutation({
    mutationFn: async (values: RetrospectiveCreateValues) => {
      const retrospective = await createRetrospective(workspaceId, {
        jobTargetId: values.targetId,
        title: values.title,
        roundLabel: values.roundLabel,
        interviewDate: values.interviewDate,
        outcome: "unrecorded",
        note: "",
      });
      const source = await addSourceVersion(workspaceId, retrospective.id, {
        sourceKind: values.sourceKind,
        body: values.body,
        fileName: values.fileName,
      });
      const receipt = await startCleanup(workspaceId, retrospective.id, source.id);
      return { retrospective, receipt };
    },
    onSuccess: async ({ retrospective, receipt }) => {
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
      patchSearch({ retrospectiveId: retrospective.id, cleanupId: receipt.cleanupVersionId, lifecycle: "active" });
      setCreateOpen(false);
      setError(null);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "新建复盘失败"),
  });
  const segmentMutation = useMutation({
    mutationFn: ({ segments, version }: { segments: SegmentEdit[]; version: number }) => updateSegments(workspaceId, selected!.id, effectiveCleanupId!, version, segments),
    onSuccess: (value) => queryClient.setQueryData(["cleanup", workspaceId, selected?.id, effectiveCleanupId], value),
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("整理结果已在其他位置更新，已为你重新载入最新版本。");
        void cleanupQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "保存修改失败");
    },
  });
  const confirmMutation = useMutation({
    mutationFn: (version: number) => confirmCleanup(workspaceId, selected!.id, effectiveCleanupId!, version),
    onSuccess: async (value) => {
      queryClient.setQueryData(["cleanup", workspaceId, selected?.id, effectiveCleanupId], value);
      await queryClient.invalidateQueries({ queryKey: ["retrospectives", workspaceId] });
    },
    onError: (reason) => {
      if (reason instanceof ApiError && reason.code === "retrospective_version_conflict") {
        setError("整理结果已在其他位置更新，已为你重新载入最新版本。");
        void cleanupQuery.refetch();
        return;
      }
      setError(reason instanceof Error ? reason.message : "确认失败");
    },
  });
  const controlMutation = useMutation({
    mutationFn: async (action: "stop" | "resume") => action === "stop" ? stopCleanup(workspaceId, selected!.id, effectiveCleanupId!) : resumeCleanup(workspaceId, selected!.id, effectiveCleanupId!),
    onSuccess: async (value) => {
      if ("cleanupVersionId" in value) patchSearch({ cleanupId: value.cleanupVersionId });
      await cleanupQuery.refetch();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "整理控制失败"),
  });

  if (!workspace) return <section className="retrospective-page retrospective-page--without-workspace"><header className="retrospective-page__header"><div><p>复盘工作台</p><h1>面试复盘</h1><span>把录音转写或事后回忆整理成可核对、可继续的复盘记录。</span></div></header><div className="retrospective-page__missing"><MessageSquareText size={32} /><h2>先选择工作区</h2><p>面试文字、整理结果和复盘记录会保存在所选工作区。</p></div></section>;
  const counts = Object.fromEntries(TABS.map((tab) => [tab.value, tab.value === lifecycle ? listQuery.data?.length ?? 0 : null]));

  return (
    <section className="retrospective-page">
      <header className="retrospective-page__header">
        <div><p>复盘工作台</p><h1>面试复盘</h1><span>把录音转写或事后回忆整理成可核对、可继续的复盘记录。</span></div>
        <Button onClick={() => setCreateOpen(true)}><Plus size={18} /> 新建复盘</Button>
      </header>
      <div className="retrospective-page__toolbar">
        <div role="tablist" aria-label="复盘生命周期">
          {TABS.map((tab) => <button type="button" role="tab" aria-selected={lifecycle === tab.value} key={tab.value} onClick={() => patchSearch({ lifecycle: tab.value, retrospectiveId: null, cleanupId: null })}><tab.icon size={16} /> {tab.label}{counts[tab.value] !== null ? ` ${counts[tab.value]}` : ""}</button>)}
        </div>
        <SelectControl aria-label="求职目标" controlSize="sm" value={targetId} onChange={(event) => patchSearch({ jobTargetId: event.target.value || null, retrospectiveId: null, cleanupId: null })} disabled={targetsQuery.isLoading || !(targetsQuery.data?.length)}>
          <option value="">全部求职目标</option>
          {(targetsQuery.data ?? []).map((target) => <option key={target.id} value={target.id}>{[target.companyName, target.roleName].filter(Boolean).join(" / ") || "岗位信息待补充"}</option>)}
        </SelectControl>
      </div>
      {error ? <div className="retrospective-page__error" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)}>关闭</button></div> : null}
      {listQuery.isError || targetsQuery.isError ? <div className="retrospective-page__error" role="alert"><span>复盘记录读取失败，请确认本地服务后重试。</span><button type="button" onClick={() => { void listQuery.refetch(); void targetsQuery.refetch(); }}>重新读取</button></div> : null}

      <TaskWorkspace className="retrospective-page__workspace" labelledBy="retrospective-page-list-title">
        <TaskWorkspacePane className="retrospective-page__list-pane" aria-label="面试复盘记录">
          <h2 id="retrospective-page-list-title">复盘记录</h2>
          <RetrospectiveList items={listQuery.data ?? []} targets={targetsQuery.data ?? []} selectedId={selected?.id} loading={listQuery.isLoading} onSelect={(id) => patchSearch({ retrospectiveId: id, cleanupId: null })} />
        </TaskWorkspacePane>
        <TaskWorkspacePane className="retrospective-page__detail-pane" scroll={false} aria-label="复盘详情">
          {cleanupQuery.data ? <CleanupWorkbench cleanup={cleanupQuery.data} busy={segmentMutation.isPending || confirmMutation.isPending || controlMutation.isPending} onSave={(segments, version) => segmentMutation.mutate({ segments, version })} onConfirm={(version) => confirmMutation.mutate(version)} onStop={() => controlMutation.mutate("stop")} onResume={() => controlMutation.mutate("resume")} /> : selected ? <RetrospectiveSummary retrospective={selected} onStart={selected.activeSourceVersionId ? async () => {
            try {
              const receipt = await startCleanup(workspaceId, selected.id, selected.activeSourceVersionId!);
              patchSearch({ retrospectiveId: selected.id, cleanupId: receipt.cleanupVersionId });
            } catch (reason) { setError(reason instanceof Error ? reason.message : "启动整理失败"); }
          } : undefined} /> : <div className="retrospective-page__empty-detail"><RotateCcw size={28} /><h2>选择一场复盘</h2><p>这里会展示整理进度、说话人校对和下一步。</p></div>}
        </TaskWorkspacePane>
      </TaskWorkspace>

      {createOpen ? <RetrospectiveCreateFlow targets={targetsQuery.data ?? []} initialTargetId={targetId} busy={createFlow.isPending} onCancel={() => setCreateOpen(false)} onCreateTarget={async (values) => {
        const target = await createJobTarget(workspaceId, values);
        await queryClient.invalidateQueries({ queryKey: ["job-targets", workspaceId] });
        return target;
      }} onSubmit={(values) => createFlow.mutate(values)} /> : null}
    </section>
  );
}

function RetrospectiveSummary({ retrospective, onStart }: { retrospective: import("./retrospectiveTypes").InterviewRetrospective; onStart?: () => void }) {
  return <div className="retrospective-summary"><span className="retrospective-summary__icon"><MessageSquareText size={24} /></span><p>{retrospective.roundLabel}</p><h2>{retrospective.title}</h2><dl><div><dt>面试日期</dt><dd>{retrospective.interviewDate?.replaceAll("-", "/") ?? "未记录"}</dd></div><div><dt>当前阶段</dt><dd>{retrospective.activeCleanupVersionId ? "整理结果已确认" : retrospective.activeSourceVersionId ? "文字已保存" : "等待文字"}</dd></div></dl>{onStart ? <Button onClick={onStart}>开始整理</Button> : null}</div>;
}
