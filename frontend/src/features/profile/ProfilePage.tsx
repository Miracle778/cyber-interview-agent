import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, CheckCircle2, FileUp, FolderLock, Upload, UserRound, X } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { cancelAgentExecution } from "../agent/agentApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { DeletionImpactDialog } from "./DeletionImpactDialog";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";
import { ProfileBackgroundTask } from "./ProfileBackgroundTask";
import { ProfileCardEditor } from "./ProfileCardEditor";
import { ProfileDocumentReader } from "./ProfileDocumentReader";
import { ProfilePendingReview } from "./ProfilePendingReview";
import { ProfileSupportReview } from "./ProfileSupportReview";
import type { ProfileSupportFilter } from "./ProfileSupportReview";
import { ResumeVersions } from "./ResumeVersions";
import { UnifiedProfileOverview } from "./UnifiedProfileOverview";
import { VersionDeletionImpactDialog } from "./VersionDeletionImpactDialog";
import type { VersionDeletionSummary } from "./VersionDeletionImpactDialog";
import { addMaterialVersion, archiveMaterial, createProfileCard, deleteProfileCard, getMaterialDocument, getMaterialVersion, getUnifiedProfile, listMaterialVersions, listProfileClaims, listProfileMaterials, materialFileDownloadUrl, restoreMaterial, retryMaterialVersion, setPrimaryVersion, updateProfileCard, updateProfilePresentation, uploadProfileMaterial } from "./profileApi";
import type { ProfileCardCategory, ProfileCardCommand, ProfileEvidence, ProfileMaterial, ProfileMaterialVersionDetail, UnifiedProfileCard } from "./profileTypes";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"];
const ACTIVE_STATUSES = new Set(["uploaded", "parsing", "parsed", "extracting"]);

type ProfileTab = "profile" | "pending" | "support" | "sources" | "agent";

function idempotencyKey(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

function validateFile(file: File) {
  const lower = file.name.toLowerCase();
  if (!SUPPORTED_EXTENSIONS.some((extension) => lower.endsWith(extension))) return "支持 PDF、DOCX、Markdown 或 TXT 文件";
  if (file.size > MAX_UPLOAD_BYTES) return "文件不能超过 10 MB";
  if (file.size === 0) return "文件内容为空，请选择其他文件";
  return null;
}

function titleFromFile(file: File) {
  return file.name.replace(/\.(pdf|docx|md|markdown|txt)$/i, "").trim() || "个人简历";
}

function errorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  return "请求没有完成，请稍后重试";
}

export function ProfilePage({ workspace }: { workspace: WorkspaceConfig | null }) {
  const client = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const workspaceId = workspace?.id ?? "";
  const [tab, setTab] = useState<ProfileTab>("profile");
  const [supportFilter, setSupportFilter] = useState<ProfileSupportFilter>("all");
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<ProfileEvidence | null>(null);
  const [documentView, setDocumentView] = useState<{ versionId: string; evidenceId?: string } | null>(null);
  const [processFocusRequest, setProcessFocusRequest] = useState(0);
  const [deletionOpen, setDeletionOpen] = useState(false);
  const [versionDeletionTarget, setVersionDeletionTarget] = useState<{ material: ProfileMaterial; version: ProfileMaterialVersionDetail } | null>(null);
  const [versionDeletionSummary, setVersionDeletionSummary] = useState<VersionDeletionSummary | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [editingCard, setEditingCard] = useState<UnifiedProfileCard | null>(null);
  const [creatingCategory, setCreatingCategory] = useState<ProfileCardCategory | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const returnState = location.state as { returnTo?: unknown; returnLabel?: unknown } | null;
  const returnTo = typeof returnState?.returnTo === "string" ? returnState.returnTo : null;
  const returnLabel = typeof returnState?.returnLabel === "string" ? returnState.returnLabel : "返回项目深挖";

  useEffect(() => { headingRef.current?.focus(); }, []);

  const materialsQuery = useQuery({
    queryKey: ["profile-materials", workspaceId],
    queryFn: ({ signal }) => listProfileMaterials(workspaceId, true, signal),
    enabled: Boolean(workspace),
    refetchInterval: (query) => ((query.state.data as ProfileMaterial[] | undefined)?.some((item) => item.latestProcessingStatus && ACTIVE_STATUSES.has(item.latestProcessingStatus)) ? 1500 : false),
  });
  const materials = useMemo(() => materialsQuery.data ?? [], [materialsQuery.data]);
  const activeMaterial = materials.find((item) => item.id === selectedMaterialId) ?? materials.find((item) => item.lifecycleStatus === "active") ?? materials[0] ?? null;

  const unifiedQuery = useQuery({
    queryKey: ["unified-profile", workspaceId],
    queryFn: ({ signal }) => getUnifiedProfile(workspaceId, signal),
    enabled: Boolean(workspace),
  });

  useEffect(() => {
    if (activeMaterial && activeMaterial.id !== selectedMaterialId) setSelectedMaterialId(activeMaterial.id);
    if (!activeMaterial) setSelectedMaterialId(null);
  }, [activeMaterial?.id]);

  const versionsQuery = useQuery({
    queryKey: ["profile-material-versions", workspaceId, activeMaterial?.id],
    queryFn: ({ signal }) => listMaterialVersions(workspaceId, activeMaterial!.id, signal),
    enabled: Boolean(workspace && activeMaterial),
    refetchInterval: (query) => ((query.state.data as { processingStatus: string }[] | undefined)?.some((item) => ACTIVE_STATUSES.has(item.processingStatus)) ? 1500 : false),
  });
  const versions = useMemo(() => versionsQuery.data ?? [], [versionsQuery.data]);

  useEffect(() => {
    if (!versions.length) { setSelectedVersionId(null); return; }
    if (!versions.some((item) => item.id === selectedVersionId)) setSelectedVersionId(activeMaterial?.currentVersionId && versions.some((item) => item.id === activeMaterial.currentVersionId) ? activeMaterial.currentVersionId : versions[0].id);
  }, [activeMaterial?.currentVersionId, selectedVersionId, versions]);

  const detailVersionId = selectedEvidence?.materialVersionId ?? selectedVersionId;
  const detailQuery = useQuery({
    queryKey: ["profile-material-version", workspaceId, detailVersionId],
    queryFn: ({ signal }) => getMaterialVersion(workspaceId, detailVersionId!, signal),
    enabled: Boolean(workspace && detailVersionId),
    refetchInterval: (query) => {
      const status = (query.state.data as { processingStatus?: string } | undefined)?.processingStatus;
      return status && ACTIVE_STATUSES.has(status) ? 1500 : false;
    },
  });
  const claimsQuery = useQuery({
    queryKey: ["profile-claims", workspaceId],
    queryFn: ({ signal }) => listProfileClaims(workspaceId, signal),
    enabled: Boolean(workspace && tab === "pending"),
  });
  const documentQuery = useQuery({
    queryKey: ["profile-material-document", workspaceId, documentView?.versionId],
    queryFn: ({ signal }) => getMaterialDocument(workspaceId, documentView!.versionId, signal),
    enabled: Boolean(workspace && documentView),
  });

  async function refreshProfile(materialId = activeMaterial?.id, versionId = selectedVersionId) {
    await client.invalidateQueries({ queryKey: ["unified-profile", workspaceId] });
    await client.invalidateQueries({ queryKey: ["profile-materials", workspaceId] });
    if (materialId) await client.invalidateQueries({ queryKey: ["profile-material-versions", workspaceId, materialId] });
    if (versionId) await client.invalidateQueries({ queryKey: ["profile-material-version", workspaceId, versionId] });
  }

  const upload = useMutation({ mutationFn: (file: File) => activeMaterial
    ? addMaterialVersion(workspaceId, activeMaterial.id, file, idempotencyKey("profile-version"))
    : uploadProfileMaterial(workspaceId, file, { title: titleFromFile(file), primaryRole: "resume" }, idempotencyKey("profile-upload")),
    onSuccess: async (result) => { setSelectedMaterialId(result.materialId); setSelectedVersionId(result.versionId); setTab("sources"); await refreshProfile(result.materialId, result.versionId); },
  });
  const retry = useMutation({ mutationFn: (versionId: string) => retryMaterialVersion(workspaceId, versionId), onSuccess: async (result) => refreshProfile(activeMaterial?.id, result.versionId) });
  const stopProcessing = useMutation({
    mutationFn: (executionId: string) => cancelAgentExecution(executionId),
    onSuccess: async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      await refreshProfile(activeMaterial?.id, selectedVersionId);
    },
  });
  const archive = useMutation({ mutationFn: (material: ProfileMaterial) => archiveMaterial(workspaceId, material), onSuccess: () => refreshProfile() });
  const restore = useMutation({ mutationFn: (material: ProfileMaterial) => restoreMaterial(workspaceId, material), onSuccess: () => refreshProfile() });
  const primary = useMutation({ mutationFn: ({ material, versionId }: { material: ProfileMaterial; versionId: string }) => setPrimaryVersion(workspaceId, material, versionId), onSuccess: () => refreshProfile() });
  const cardWrite = useMutation({
    mutationFn: ({ card, command }: { card: UnifiedProfileCard | null; command: Omit<ProfileCardCommand, "workspaceId"> }) => card
      ? updateProfileCard(card.claimId, { workspaceId, ...command })
      : createProfileCard({ workspaceId, ...command }),
    onSuccess: async () => {
      setEditingCard(null);
      setCreatingCategory(null);
      setEditorError(null);
      await client.invalidateQueries({ queryKey: ["unified-profile", workspaceId] });
    },
    onError: (error) => setEditorError(errorMessage(error)),
  });
  const cardDelete = useMutation({
    mutationFn: (card: UnifiedProfileCard) => deleteProfileCard(workspaceId, card.claimId, card.version),
    onSuccess: async () => {
      setEditingCard(null);
      setEditorError(null);
      await client.invalidateQueries({ queryKey: ["unified-profile", workspaceId] });
    },
    onError: (error) => setEditorError(errorMessage(error)),
  });
  const presentation = useMutation({
    mutationFn: (claimId: string) => {
      const profile = unifiedQuery.data;
      if (!profile) throw new Error("个人画像尚未加载完成");
      return updateProfilePresentation(workspaceId, {
        summaryClaimId: profile.summary?.claimId ?? null,
        primaryDirectionClaimId: claimId,
        featuredClaimIds: profile.highlights.slice(0, 5).map((item) => item.claimId),
        version: profile.presentationVersion,
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["unified-profile", workspaceId] }),
  });

  async function acceptFile(file: File | undefined) {
    if (!file) return;
    const validation = validateFile(file);
    setFileError(validation);
    if (validation) return;
    await upload.mutateAsync(file).catch(() => undefined);
  }

  function chooseFile() {
    setFileError(null);
    inputRef.current?.click();
  }

  if (!workspace) return <div className="profile-workspace-missing"><FolderLock size={28} /><h1 tabIndex={-1}>个人画像</h1><p>请先初始化工作区，再建立你的个人资料。</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  const queryError = unifiedQuery.error ?? materialsQuery.error ?? versionsQuery.error ?? detailQuery.error;
  const mutationError = upload.error ?? retry.error ?? archive.error ?? restore.error ?? primary.error ?? presentation.error;
  const busy = upload.isPending || retry.isPending || archive.isPending || restore.isPending || primary.isPending || stopProcessing.isPending;
  const detail = detailQuery.data ?? null;
  const workbenchMode = Boolean(documentView) || tab === "sources" || tab === "pending" || tab === "support" || tab === "agent";
  const supportReviewCount = unifiedQuery.data ? [
    ...(unifiedQuery.data.summary ? [unifiedQuery.data.summary] : []),
    ...unifiedQuery.data.directions,
    ...unifiedQuery.data.highlights,
    ...unifiedQuery.data.experiences,
    ...unifiedQuery.data.projects,
    ...unifiedQuery.data.skills,
    ...unifiedQuery.data.education,
    ...unifiedQuery.data.certifications,
    ...unifiedQuery.data.achievements,
    ...unifiedQuery.data.links,
  ].filter((card) => ["related", "conflicted", "unsupported"].includes(card.supportStatus)).length : 0;
  const confirmedProfileCount = unifiedQuery.data ? (
    unifiedQuery.data.experiences.length
    + unifiedQuery.data.projects.length
    + unifiedQuery.data.skills.length
    + unifiedQuery.data.education.length
    + unifiedQuery.data.certifications.length
    + unifiedQuery.data.achievements.length
  ) : null;

  return <section className={`profile-shell ${workbenchMode ? "profile-shell--workbench" : "profile-shell--reading"} ${tab === "agent" && !documentView ? "profile-shell--agent" : ""}`}>
    <header className="profile-header">
      <div>{returnTo ? <Button variant="secondary" size="sm" className="profile-header__return" onClick={() => navigate(returnTo)}><ArrowLeft size={15} />{returnLabel}</Button> : null}<h1 ref={headingRef} tabIndex={-1}>个人画像</h1><p>集中管理你的经历、项目和技能，供岗位分析、简历优化与面试训练使用。</p></div>
      <div className="profile-header__summary"><UserRound size={16} /><span>{confirmedProfileCount === null ? "正在读取" : `${confirmedProfileCount} 条已确认资料`}</span></div>
    </header>
    <nav className="profile-tabs" aria-label="个人画像页面">
      <button type="button" aria-current={tab === "profile" && !documentView ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setDocumentView(null); setTab("profile"); }}>我的画像</button>
      <button type="button" aria-current={tab === "pending" && !documentView ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setDocumentView(null); setTab("pending"); }}>待确认{unifiedQuery.data?.pendingCount ? ` ${unifiedQuery.data.pendingCount}` : ""}</button>
      <button type="button" aria-current={tab === "support" && !documentView ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setDocumentView(null); setSupportFilter("all"); setTab("support"); }}>来源核对{supportReviewCount ? ` ${supportReviewCount}` : ""}</button>
      <button type="button" aria-current={tab === "sources" && !documentView ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setDocumentView(null); setTab("sources"); }}>简历与来源</button>
      <button type="button" aria-current={tab === "agent" && !documentView ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setDocumentView(null); setTab("agent"); }}>画像助手</button>
    </nav>

    <input ref={inputRef} className="profile-file-input" aria-label="选择简历文件" type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => { void acceptFile(event.target.files?.[0]); event.currentTarget.value = ""; }} />

    <ProfileBackgroundTask
      detail={detail}
      stopping={stopProcessing.isPending}
      continuing={retry.isPending}
      onOpen={() => {
        setSelectedEvidence(null);
        setDocumentView(null);
        setTab("sources");
        setProcessFocusRequest((value) => value + 1);
      }}
      onStop={() => { if (detail?.execution?.id) stopProcessing.mutate(detail.execution.id); }}
      onContinue={() => { if (detail) retry.mutate(detail.id); }}
      onOpenPending={() => { setSelectedEvidence(null); setDocumentView(null); setTab("pending"); }}
    />

    <div className="profile-page-content">
      {queryError && (unifiedQuery.isError || materialsQuery.isError) ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>个人资料读取失败</strong><p>{errorMessage(queryError)}</p></div><Button variant="secondary" onClick={() => { void unifiedQuery.refetch(); void materialsQuery.refetch(); }}>重新读取</Button></div> : null}
      {mutationError || fileError ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>{fileError ? "无法上传这个文件" : "操作没有完成"}</strong><p>{fileError ?? errorMessage(mutationError)}</p></div></div> : null}
      {!documentView && versionDeletionSummary ? <section className="profile-version-deletion-result" role="status">
        <CheckCircle2 size={22} />
        <div>
          <strong>已删除 v{versionDeletionSummary.versionNumber}“{versionDeletionSummary.fileName}”</strong>
          <p>
            画像移除 {versionDeletionSummary.deletedClaimTitles.length} 条；
            保留但缺少来源依据 {versionDeletionSummary.retainedUnsupportedClaimTitles.length} 条；
            仍有其他来源支持 {versionDeletionSummary.retainedSupportedClaimTitles.length} 条。
          </p>
          {versionDeletionSummary.deletedClaimTitles.length
            || versionDeletionSummary.retainedUnsupportedClaimTitles.length
            || versionDeletionSummary.retainedSupportedClaimTitles.length
            ? <details>
              <summary>查看具体变化</summary>
              {versionDeletionSummary.deletedClaimTitles.length ? <div><b>已从画像移除</b><span>{versionDeletionSummary.deletedClaimTitles.join("、")}</span></div> : null}
              {versionDeletionSummary.retainedUnsupportedClaimTitles.length ? <div><b>保留，但需要补充来源</b><span>{versionDeletionSummary.retainedUnsupportedClaimTitles.join("、")}</span></div> : null}
              {versionDeletionSummary.retainedSupportedClaimTitles.length ? <div><b>内容不变，仍有其他来源</b><span>{versionDeletionSummary.retainedSupportedClaimTitles.join("、")}</span></div> : null}
            </details>
            : null}
        </div>
        <div className="profile-version-deletion-result__actions">
          <Button variant="secondary" size="sm" onClick={() => { setSelectedEvidence(null); setDocumentView(null); setTab("profile"); }}>查看我的画像</Button>
          <button type="button" aria-label="关闭版本删除结果" onClick={() => setVersionDeletionSummary(null)}><X size={17} /></button>
        </div>
      </section> : null}

    {!materialsQuery.isLoading && !materialsQuery.isError && !activeMaterial && tab === "sources" ? <section className="profile-empty" data-testid="profile-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void acceptFile(event.dataTransfer.files[0]); }}>
      <span><FileUp size={28} /></span><h2>还没有简历</h2><p>拖入简历，或从电脑选择 PDF、DOCX、Markdown、TXT 文件。上传后会依次完成文本提取、隐私处理和简历要点整理。</p><Button loading={upload.isPending} onClick={chooseFile}><Upload size={16} />选择简历文件</Button><small>单个文件不超过 10 MB；原文件默认仅自己可见。</small>
    </section> : null}

    {documentView && documentQuery.isLoading ? <div className="profile-loading" role="status"><p>正在打开完整简历…</p></div> : null}
    {documentView && documentQuery.isError ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>完整简历暂时无法打开</strong><p>{errorMessage(documentQuery.error)}</p></div><Button variant="secondary" onClick={() => void documentQuery.refetch()}>重新读取</Button></div> : null}
    {documentView && documentQuery.data ? <ProfileDocumentReader document={documentQuery.data} focusEvidenceId={documentView.evidenceId} downloadUrl={materialFileDownloadUrl(workspaceId, documentView.versionId)} onBack={() => { setDocumentView(null); setSelectedEvidence(null); }} /> : null}
    {!documentView && tab === "profile" ? <UnifiedProfileOverview profile={unifiedQuery.data ?? null} loading={unifiedQuery.isLoading} onUpload={chooseFile} onCreate={(category = "project") => { setEditorError(null); setCreatingCategory(category); setEditingCard(null); }} onEdit={(card) => { setEditorError(null); setEditingCard(card); setCreatingCategory(null); }} onOpenPending={() => setTab("pending")} onOpenSupportReview={(filter) => { setSupportFilter(filter); setTab("support"); }} onSetPrimaryDirection={(claimId) => presentation.mutate(claimId)} /> : null}
    {!documentView && tab === "support" ? <ProfileSupportReview profile={unifiedQuery.data ?? null} loading={unifiedQuery.isLoading} initialFilter={supportFilter} onEdit={(card) => { setEditorError(null); setEditingCard(card); setCreatingCategory(null); }} /> : null}
    {activeMaterial && !documentView && tab === "sources" ? <ResumeVersions materials={materials} versions={versions} selectedMaterialId={activeMaterial.id} selectedVersionId={selectedVersionId} detail={detail} pendingProposalCount={unifiedQuery.data?.pendingCount ?? null} busy={busy} onSelectMaterial={(id) => { setSelectedMaterialId(id); setSelectedVersionId(null); }} onSelectVersion={setSelectedVersionId} onRetry={(id) => retry.mutate(id)} onArchive={(item) => archive.mutate(item)} onRestore={(item) => restore.mutate(item)} onSetPrimary={(item, versionId) => primary.mutate({ material: item, versionId })} onPermanentDelete={() => setDeletionOpen(true)} onPermanentDeleteVersion={(item, version) => setVersionDeletionTarget({ material: item, version })} onOpenDocument={(evidenceId) => { if (selectedVersionId) setDocumentView({ versionId: selectedVersionId, ...(evidenceId ? { evidenceId } : {}) }); }} onAddVersion={chooseFile} processFocusRequest={processFocusRequest} /> : null}
    {!documentView && tab === "pending" ? <ProfilePendingReview workspaceId={workspaceId} snapshot={claimsQuery.data ?? null} loading={claimsQuery.isLoading} onRefresh={async () => { await Promise.all([claimsQuery.refetch(), refreshProfile()]); }} onOpenEvidence={(evidence) => { setSelectedEvidence(evidence); setDocumentView({ versionId: evidence.materialVersionId, evidenceId: evidence.id }); }} /> : null}
    {activeMaterial ? <DeletionImpactDialog open={deletionOpen} workspaceId={workspaceId} material={activeMaterial} onClose={() => setDeletionOpen(false)} onDeleted={() => { setDeletionOpen(false); setTab("profile"); void refreshProfile(activeMaterial.id, selectedVersionId); void claimsQuery.refetch(); }} /> : null}
    {versionDeletionTarget ? <VersionDeletionImpactDialog
      open
      workspaceId={workspaceId}
      material={versionDeletionTarget.material}
      version={versionDeletionTarget.version}
      onClose={() => setVersionDeletionTarget(null)}
      onDeleted={(_result, replacementVersionId, summary) => {
        const deletedVersionId = versionDeletionTarget.version.id;
        const nextVersionId = replacementVersionId
          ?? (versionDeletionTarget.material.currentVersionId !== deletedVersionId ? versionDeletionTarget.material.currentVersionId : null)
          ?? versions.find((item) => item.id !== deletedVersionId)?.id
          ?? null;
        setVersionDeletionTarget(null);
        setVersionDeletionSummary(summary);
        setSelectedVersionId(nextVersionId);
        client.removeQueries({ queryKey: ["profile-material-version", workspaceId, deletedVersionId] });
        void refreshProfile(versionDeletionTarget.material.id, nextVersionId);
        void claimsQuery.refetch();
      }}
    /> : null}
    {!documentView && tab === "agent" ? <ProfileAgentWorkspace workspaceId={workspaceId} focus={{ ...(activeMaterial ? { materialId: activeMaterial.id } : {}), ...(selectedVersionId ? { materialVersionId: selectedVersionId } : {}) }} onOpenPending={() => setTab("pending")} /> : null}
      {editingCard || creatingCategory ? <ProfileCardEditor card={editingCard} initialCategory={creatingCategory ?? editingCard?.category ?? "project"} busy={cardWrite.isPending || cardDelete.isPending} error={editorError} onSave={async (command) => { await cardWrite.mutateAsync({ card: editingCard, command }).catch(() => undefined); }} onDelete={editingCard ? async () => { await cardDelete.mutateAsync(editingCard).catch(() => undefined); } : undefined} onCancel={() => { if (!cardWrite.isPending && !cardDelete.isPending) { setEditingCard(null); setCreatingCategory(null); setEditorError(null); } }} /> : null}
    </div>
  </section>;
}
