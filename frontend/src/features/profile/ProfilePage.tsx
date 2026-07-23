import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileUp, FolderLock, Upload, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { EvidenceDetail } from "./EvidenceDetail";
import { ClaimReview } from "./ClaimReview";
import { DeletionImpactDialog } from "./DeletionImpactDialog";
import { ProfileOverview } from "./ProfileOverview";
import { ProfileAgentWorkspace } from "./ProfileAgentWorkspace";
import { ResumeVersions } from "./ResumeVersions";
import { addMaterialVersion, archiveMaterial, getMaterialVersion, listMaterialVersions, listProfileClaims, listProfileMaterials, restoreMaterial, retryMaterialVersion, setPrimaryVersion, uploadProfileMaterial } from "./profileApi";
import type { ProfileEvidence, ProfileMaterial } from "./profileTypes";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"];
const ACTIVE_STATUSES = new Set(["uploaded", "parsing", "parsed", "extracting"]);

type ProfileTab = "overview" | "versions" | "claims" | "agent";

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
  const [tab, setTab] = useState<ProfileTab>("overview");
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<ProfileEvidence | null>(null);
  const [deletionOpen, setDeletionOpen] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => { headingRef.current?.focus(); }, []);

  const materialsQuery = useQuery({
    queryKey: ["profile-materials", workspaceId],
    queryFn: ({ signal }) => listProfileMaterials(workspaceId, true, signal),
    enabled: Boolean(workspace),
    refetchInterval: (query) => ((query.state.data as ProfileMaterial[] | undefined)?.some((item) => item.latestProcessingStatus && ACTIVE_STATUSES.has(item.latestProcessingStatus)) ? 1500 : false),
  });
  const materials = useMemo(() => materialsQuery.data ?? [], [materialsQuery.data]);
  const activeMaterial = materials.find((item) => item.id === selectedMaterialId) ?? materials.find((item) => item.lifecycleStatus === "active") ?? materials[0] ?? null;

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
    enabled: Boolean(workspace && tab === "claims"),
  });

  async function refreshProfile(materialId = activeMaterial?.id, versionId = selectedVersionId) {
    await client.invalidateQueries({ queryKey: ["profile-materials", workspaceId] });
    if (materialId) await client.invalidateQueries({ queryKey: ["profile-material-versions", workspaceId, materialId] });
    if (versionId) await client.invalidateQueries({ queryKey: ["profile-material-version", workspaceId, versionId] });
  }

  const upload = useMutation({ mutationFn: (file: File) => activeMaterial
    ? addMaterialVersion(workspaceId, activeMaterial.id, file, idempotencyKey("profile-version"))
    : uploadProfileMaterial(workspaceId, file, { title: titleFromFile(file), primaryRole: "resume" }, idempotencyKey("profile-upload")),
    onSuccess: async (result) => { setSelectedMaterialId(result.materialId); setSelectedVersionId(result.versionId); setTab("versions"); await refreshProfile(result.materialId, result.versionId); },
  });
  const retry = useMutation({ mutationFn: (versionId: string) => retryMaterialVersion(workspaceId, versionId), onSuccess: async (result) => refreshProfile(activeMaterial?.id, result.versionId) });
  const archive = useMutation({ mutationFn: (material: ProfileMaterial) => archiveMaterial(workspaceId, material), onSuccess: () => refreshProfile() });
  const restore = useMutation({ mutationFn: (material: ProfileMaterial) => restoreMaterial(workspaceId, material), onSuccess: () => refreshProfile() });
  const primary = useMutation({ mutationFn: ({ material, versionId }: { material: ProfileMaterial; versionId: string }) => setPrimaryVersion(workspaceId, material, versionId), onSuccess: () => refreshProfile() });

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

  if (!workspace) return <div className="profile-workspace-missing"><FolderLock size={28} /><h1 tabIndex={-1}>个人资料</h1><p>请先初始化工作区，再导入简历和管理个人画像。</p><Link className="text-link" to="/settings">前往设置</Link></div>;

  const queryError = materialsQuery.error ?? versionsQuery.error ?? detailQuery.error;
  const mutationError = upload.error ?? retry.error ?? archive.error ?? restore.error ?? primary.error;
  const busy = upload.isPending || retry.isPending || archive.isPending || restore.isPending || primary.isPending;
  const detail = detailQuery.data ?? null;
  const selectedEvidenceValue = selectedEvidence && detail?.evidencePage.items.find((item) => item.id === selectedEvidence.id) || selectedEvidence;

  return <section className="profile-shell">
    <header className="profile-header">
      <div><h1 ref={headingRef} tabIndex={-1}>个人资料</h1><p>管理简历版本、可追溯证据和待确认的个人画像。</p></div>
      <div className="profile-header__summary"><UserRound size={16} /><span>{materials.filter((item) => item.lifecycleStatus === "active").length} 份有效材料</span></div>
    </header>
    <nav className="profile-tabs" aria-label="个人资料页面">
      <button type="button" aria-current={tab === "overview" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("overview"); }}>资料总览</button>
      <button type="button" aria-current={tab === "versions" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("versions"); }}>简历版本</button>
      <button type="button" aria-current={tab === "claims" && !selectedEvidence ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("claims"); }}>画像与经历</button>
      <button type="button" aria-current={tab === "agent" ? "page" : undefined} onClick={() => { setSelectedEvidence(null); setTab("agent"); }}>Agent 会话</button>
    </nav>

    <input ref={inputRef} className="profile-file-input" aria-label="选择简历文件" type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => { void acceptFile(event.target.files?.[0]); event.currentTarget.value = ""; }} />

    {queryError && materialsQuery.isError ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>个人材料读取失败</strong><p>{errorMessage(queryError)}</p></div><Button variant="secondary" onClick={() => materialsQuery.refetch()}>重新读取</Button></div> : null}
    {mutationError || fileError ? <div className="profile-page-error" role="alert"><AlertCircle size={21} /><div><strong>{fileError ? "无法上传这个文件" : "操作没有完成"}</strong><p>{fileError ?? errorMessage(mutationError)}</p></div></div> : null}

    {materialsQuery.isLoading ? <div className="profile-loading" role="status"><span className="profile-loading__bar" /><span className="profile-loading__bar" /><p>正在读取个人材料…</p></div> : null}

    {!materialsQuery.isLoading && !materialsQuery.isError && !activeMaterial && tab !== "agent" ? <section className="profile-empty" data-testid="profile-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void acceptFile(event.dataTransfer.files[0]); }}>
      <span><FileUp size={28} /></span><h2>还没有个人材料</h2><p>拖入简历，或从电脑选择 PDF、DOCX、Markdown、TXT 文件。上传后会依次完成文本提取、脱敏和 Claim 提取。</p><Button loading={upload.isPending} onClick={chooseFile}><Upload size={16} />选择简历文件</Button><small>单个文件不超过 10 MB；原文件默认仅自己可见。</small>
    </section> : null}

    {activeMaterial && selectedEvidenceValue && detail ? <EvidenceDetail materialTitle={detail.material.title} versionNumber={detail.versionNumber} evidence={selectedEvidenceValue} onBack={() => setSelectedEvidence(null)} /> : null}
    {activeMaterial && !selectedEvidenceValue && tab === "overview" ? <ProfileOverview material={activeMaterial} detail={detail} onImport={chooseFile} onOpenVersions={() => setTab("versions")} onOpenEvidence={(evidenceId) => { const evidence = detail?.evidencePage.items.find((item) => item.id === evidenceId); if (evidence) setSelectedEvidence(evidence); }} /> : null}
    {activeMaterial && !selectedEvidenceValue && tab === "versions" ? <ResumeVersions materials={materials} versions={versions} selectedMaterialId={activeMaterial.id} selectedVersionId={selectedVersionId} detail={detail} busy={busy} onSelectMaterial={(id) => { setSelectedMaterialId(id); setSelectedVersionId(null); }} onSelectVersion={setSelectedVersionId} onRetry={(id) => retry.mutate(id)} onArchive={(item) => archive.mutate(item)} onRestore={(item) => restore.mutate(item)} onSetPrimary={(item, versionId) => primary.mutate({ material: item, versionId })} onOpenEvidence={setSelectedEvidence} onAddVersion={chooseFile} /> : null}
    {activeMaterial && !selectedEvidenceValue && tab === "claims" ? <ClaimReview workspaceId={workspaceId} snapshot={claimsQuery.data ?? null} loading={claimsQuery.isLoading} onRefresh={() => claimsQuery.refetch()} onOpenEvidence={setSelectedEvidence} onOpenDeletion={() => setDeletionOpen(true)} /> : null}
    {activeMaterial ? <DeletionImpactDialog open={deletionOpen} workspaceId={workspaceId} material={activeMaterial} onClose={() => setDeletionOpen(false)} onDeleted={() => { setDeletionOpen(false); setTab("overview"); void refreshProfile(activeMaterial.id, selectedVersionId); void claimsQuery.refetch(); }} /> : null}
    {!selectedEvidenceValue && tab === "agent" ? <ProfileAgentWorkspace workspaceId={workspaceId} focus={{ ...(activeMaterial ? { materialId: activeMaterial.id } : {}), ...(selectedVersionId ? { materialVersionId: selectedVersionId } : {}) }} /> : null}
  </section>;
}
