import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileUp, FolderLock, Upload, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { EvidenceDetail } from "./EvidenceDetail";
import { DeletionImpactDialog } from "./DeletionImpactDialog";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";
import { ProfileCardEditor } from "./ProfileCardEditor";
import { ProfilePendingReview } from "./ProfilePendingReview";
import { ResumeVersions } from "./ResumeVersions";
import { UnifiedProfileOverview } from "./UnifiedProfileOverview";
import { addMaterialVersion, archiveMaterial, createProfileCard, deleteProfileCard, getMaterialVersion, getUnifiedProfile, listMaterialVersions, listProfileClaims, listProfileMaterials, restoreMaterial, retryMaterialVersion, setPrimaryVersion, updateProfileCard, updateProfilePresentation, uploadProfileMaterial } from "./profileApi";
import type { ProfileCardCategory, ProfileCardCommand, ProfileEvidence, ProfileMaterial, UnifiedProfileCard } from "./profileTypes";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"];
const ACTIVE_STATUSES = new Set(["uploaded", "parsing", "parsed", "extracting"]);

type ProfileTab = "profile" | "pending" | "sources" | "agent";

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
  const inputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const workspaceId = workspace?.id ?? "";
  const [tab, setTab] = useState<ProfileTab>("profile");
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<ProfileEvidence | null>(null);
  const [deletionOpen, setDeletionOpen] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [editingCard, setEditingCard] = useState<UnifiedProfileCard | null>(null);
  const [creatingCategory, setCreatingCategory] = useState<ProfileCardCategory | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);

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
  const busy = upload.isPending || retry.isPending || archive.isPending || restore.isPending || primary.isPending;
  const detail = detailQuery.data ?? null;
  const selectedEvidenceValue = selectedEvidence && detail?.evidencePage.items.find((item) => item.id === selectedEvidence.id) || selectedEvidence;

  return <section className="profile-shell">
    <header className="profile-header">
      <div><h1 ref={headingRef} tabIndex={-1}>个人画像</h1><p>集中管理你的经历、项目和技能，供岗位分析、简历优化与面试训练使用。</p></div>
      <div className="profile-header__summary"><UserRound size={16} /><span>{unifiedQuery.data ? `${unifiedQuery.data.experiences.length + unifiedQuery.data.projects.length + unifiedQuery.data.skills.length} 条核心资料` : "正在读取"}</span></div>
    </header>
    <nav className="profile-tabs" aria-label="个人画像页面">
      <button type="button" aria-current={tab === "profile" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("profile"); }}>我的画像</button>
      <button type="button" aria-current={tab === "pending" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("pending"); }}>待确认{unifiedQuery.data?.pendingCount ? ` ${unifiedQuery.data.pendingCount}` : ""}</button>
      <button type="button" aria-current={tab === "sources" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("sources"); }}>简历与来源</button>
      <button type="button" aria-current={tab === "agent" ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("agent"); }}>画像助手</button>
    </nav>

    <input ref={inputRef} className="profile-file-input" aria-label="选择简历文件" type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => { void acceptFile(event.target.files?.[0]); event.currentTarget.value = ""; }} />

    {queryError && (unifiedQuery.isError || materialsQuery.isError) ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>个人资料读取失败</strong><p>{errorMessage(queryError)}</p></div><Button variant="secondary" onClick={() => { void unifiedQuery.refetch(); void materialsQuery.refetch(); }}>重新读取</Button></div> : null}
    {mutationError || fileError ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>{fileError ? "无法上传这个文件" : "操作没有完成"}</strong><p>{fileError ?? errorMessage(mutationError)}</p></div></div> : null}

    {!materialsQuery.isLoading && !materialsQuery.isError && !activeMaterial && tab === "sources" ? <section className="profile-empty" data-testid="profile-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void acceptFile(event.dataTransfer.files[0]); }}>
      <span><FileUp size={28} /></span><h2>还没有简历</h2><p>拖入简历，或从电脑选择 PDF、DOCX、Markdown、TXT 文件。上传后会依次完成文本提取、隐私处理和简历要点整理。</p><Button loading={upload.isPending} onClick={chooseFile}><Upload size={16} />选择简历文件</Button><small>单个文件不超过 10 MB；原文件默认仅自己可见。</small>
    </section> : null}

    {activeMaterial && selectedEvidenceValue && detail ? <EvidenceDetail materialTitle={detail.material.title} versionNumber={detail.versionNumber} evidence={selectedEvidenceValue} onBack={() => setSelectedEvidence(null)} /> : null}
    {!selectedEvidenceValue && tab === "profile" ? <UnifiedProfileOverview profile={unifiedQuery.data ?? null} loading={unifiedQuery.isLoading} onUpload={chooseFile} onCreate={(category = "project") => { setEditorError(null); setCreatingCategory(category); setEditingCard(null); }} onEdit={(card) => { setEditorError(null); setEditingCard(card); setCreatingCategory(null); }} onOpenPending={() => setTab("pending")} onSetPrimaryDirection={(claimId) => presentation.mutate(claimId)} /> : null}
    {activeMaterial && !selectedEvidenceValue && tab === "sources" ? <ResumeVersions materials={materials} versions={versions} selectedMaterialId={activeMaterial.id} selectedVersionId={selectedVersionId} detail={detail} busy={busy} onSelectMaterial={(id) => { setSelectedMaterialId(id); setSelectedVersionId(null); }} onSelectVersion={setSelectedVersionId} onRetry={(id) => retry.mutate(id)} onArchive={(item) => archive.mutate(item)} onRestore={(item) => restore.mutate(item)} onSetPrimary={(item, versionId) => primary.mutate({ material: item, versionId })} onPermanentDelete={() => setDeletionOpen(true)} onOpenEvidence={setSelectedEvidence} onAddVersion={chooseFile} /> : null}
    {!selectedEvidenceValue && tab === "pending" ? <ProfilePendingReview workspaceId={workspaceId} snapshot={claimsQuery.data ?? null} loading={claimsQuery.isLoading} onRefresh={async () => { await claimsQuery.refetch(); await unifiedQuery.refetch(); }} onOpenEvidence={setSelectedEvidence} /> : null}
    {activeMaterial ? <DeletionImpactDialog open={deletionOpen} workspaceId={workspaceId} material={activeMaterial} onClose={() => setDeletionOpen(false)} onDeleted={() => { setDeletionOpen(false); setTab("profile"); void refreshProfile(activeMaterial.id, selectedVersionId); void claimsQuery.refetch(); }} /> : null}
    {!selectedEvidenceValue && tab === "agent" ? <ProfileAgentWorkspace workspaceId={workspaceId} focus={{ ...(activeMaterial ? { materialId: activeMaterial.id } : {}), ...(selectedVersionId ? { materialVersionId: selectedVersionId } : {}) }} onOpenPending={() => setTab("pending")} /> : null}
    {editingCard || creatingCategory ? <ProfileCardEditor card={editingCard} initialCategory={creatingCategory ?? editingCard?.category ?? "project"} busy={cardWrite.isPending || cardDelete.isPending} error={editorError} onSave={async (command) => { await cardWrite.mutateAsync({ card: editingCard, command }).catch(() => undefined); }} onDelete={editingCard ? async () => { await cardDelete.mutateAsync(editingCard).catch(() => undefined); } : undefined} onCancel={() => { if (!cardWrite.isPending && !cardDelete.isPending) { setEditingCard(null); setCreatingCategory(null); setEditorError(null); } }} /> : null}
  </section>;
}
