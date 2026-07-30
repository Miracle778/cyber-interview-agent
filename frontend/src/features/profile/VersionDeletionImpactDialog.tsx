import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, FileMinus2, X } from "lucide-react";
import { formatBeijingTime } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { permanentlyDeleteMaterialVersion, previewMaterialVersionDeletion } from "./profileApi";
import { profileClaimTypeLabel } from "./profilePresentation";
import type { MaterialVersionDeletionPreview, PermanentMaterialDeletionResult, ProfileMaterial, ProfileMaterialVersionDetail } from "./profileTypes";

const CONFIRM_TEXT = "删除此版本";
type ClaimDeletionAction = "delete" | "retain_unsupported";
type AffectedClaim = MaterialVersionDeletionPreview["affectedClaims"][number];

const claimFieldLabels: Record<string, string> = {
  name: "名称",
  title: "名称",
  role: "担任角色",
  company: "公司",
  organization: "组织",
  school: "学校",
  degree: "学历",
  major: "专业",
  description: "具体内容",
  confidence: "识别可信度",
  tech_stack: "使用技术",
  skills: "相关技能",
  key_actions: "关键行动",
  responsibilities: "主要职责",
  result: "成果",
  results: "成果",
  achievements: "成果",
  highlights: "亮点",
  issuer: "颁发机构",
  date: "时间",
  location: "地点",
  start_date: "开始时间",
  end_date: "结束时间",
  url: "链接",
};

function formatClaimValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join("、");
  if (value && typeof value === "object") return Object.values(value).map(String).join("、");
  return String(value ?? "未填写");
}

function claimTitle(claim: AffectedClaim) {
  const value = claim.value ?? {};
  const preferred = claim.claimType === "experience"
    ? value.company ?? value.organization ?? value.role
    : claim.claimType === "education"
      ? value.school ?? value.organization ?? value.major
      : value.name ?? value.title ?? value.skill ?? value.role ?? value.url;
  return typeof preferred === "string" && preferred.trim()
    ? preferred
    : profileClaimTypeLabel(claim.claimType);
}

function claimDetailRows(claim: AffectedClaim) {
  return Object.entries(claim.value ?? {})
    .filter(([key, value]) => key !== "category" && value !== null && value !== "")
    .map(([key, value]) => ({
      key,
      label: claimFieldLabels[key] ?? key.replaceAll("_", " "),
      value: formatClaimValue(value),
    }));
}

interface VersionDeletionImpactDialogProps {
  open: boolean;
  workspaceId: string;
  material: ProfileMaterial;
  version: ProfileMaterialVersionDetail;
  onClose: () => void;
  onDeleted: (result: PermanentMaterialDeletionResult, nextVersionId: string | null, summary: VersionDeletionSummary) => void;
}

export interface VersionDeletionSummary {
  versionNumber: number;
  fileName: string;
  deletedClaimTitles: string[];
  retainedUnsupportedClaimTitles: string[];
  retainedSupportedClaimTitles: string[];
}

export function VersionDeletionImpactDialog({ open, workspaceId, material, version, onClose, onDeleted }: VersionDeletionImpactDialogProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [preview, setPreview] = useState<MaterialVersionDeletionPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, ClaimDeletionAction>>({});
  const [selectedClaimIds, setSelectedClaimIds] = useState<string[]>([]);
  const [expandedClaimIds, setExpandedClaimIds] = useState<string[]>([]);
  const [replacementVersionId, setReplacementVersionId] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setPreview(null);
    setChoices({});
    setSelectedClaimIds([]);
    setExpandedClaimIds([]);
    setReplacementVersionId("");
    setConfirmText("");
    setError(null);
    setBusy(true);
    void previewMaterialVersionDeletion(workspaceId, material, version.id).then((result) => {
      setPreview(result);
      setChoices(Object.fromEntries(result.affectedClaims.map((claim) => [claim.claimId, "retain_unsupported"])));
      setReplacementVersionId(result.isCurrentVersion ? result.replacementVersions[0]?.id ?? "" : "");
    }).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "删除影响读取失败");
    }).finally(() => setBusy(false));
    queueMicrotask(() => closeRef.current?.focus());
    return () => returnFocusRef.current?.focus();
  }, [open, workspaceId, material.id, material.version, version.id]);

  if (!open) return null;

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled])') ?? [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function remove() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const nextVersionId = preview.isCurrentVersion ? replacementVersionId : null;
      const result = await permanentlyDeleteMaterialVersion(
        workspaceId,
        material,
        preview,
        nextVersionId,
        Object.entries(choices).map(([claimId, action]) => ({ claimId, action })),
        "not_applicable",
      );
      onDeleted(result, nextVersionId, {
        versionNumber: preview.versionNumber,
        fileName: version.fileName,
        deletedClaimTitles: affectedClaims
          .filter((claim) => choices[claim.claimId] === "delete")
          .map(claimTitle),
        retainedUnsupportedClaimTitles: affectedClaims
          .filter((claim) => choices[claim.claimId] === "retain_unsupported" && claim.remainingEvidenceIds.length === 0)
          .map(claimTitle),
        retainedSupportedClaimTitles: affectedClaims
          .filter((claim) => choices[claim.claimId] === "retain_unsupported" && claim.remainingEvidenceIds.length > 0)
          .map(claimTitle),
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "版本删除没有完成");
    } finally {
      setBusy(false);
    }
  }

  const hasActiveDependency = Boolean(preview?.activePublicationIds.length);
  const protectedDelete = preview?.affectedClaims.some((claim) => claim.selectionIds.length && choices[claim.claimId] === "delete");
  const replacementMissing = Boolean(preview?.isCurrentVersion && !replacementVersionId);
  const canDelete = Boolean(preview && confirmText === CONFIRM_TEXT && !hasActiveDependency && !protectedDelete && !replacementMissing);
  const affectedClaims = preview?.affectedClaims ?? [];
  const selectedClaimIdSet = new Set(selectedClaimIds);
  const allClaimsSelected = affectedClaims.length > 0 && affectedClaims.every((claim) => selectedClaimIdSet.has(claim.claimId));
  const selectedClaims = affectedClaims.filter((claim) => selectedClaimIdSet.has(claim.claimId));
  const selectedProtectedCount = selectedClaims.filter((claim) => claim.selectionIds.length > 0).length;
  const selectedActions = new Set(selectedClaims.map((claim) => choices[claim.claimId]));
  const bulkChoice: ClaimDeletionAction | "mixed" = selectedActions.size === 1
    ? (selectedActions.values().next().value as ClaimDeletionAction)
    : "mixed";

  function toggleClaimSelection(claimId: string, checked: boolean) {
    setSelectedClaimIds((current) => checked
      ? [...new Set([...current, claimId])]
      : current.filter((id) => id !== claimId));
  }

  function applyBulkChoice(action: ClaimDeletionAction) {
    if (!selectedClaims.length) return;
    setChoices((current) => ({
      ...current,
      ...Object.fromEntries(selectedClaims.map((claim) => [
        claim.claimId,
        action === "delete" && claim.selectionIds.length ? "retain_unsupported" : action,
      ])),
    }));
  }

  function toggleClaimDetails(claimId: string) {
    setExpandedClaimIds((current) => current.includes(claimId)
      ? current.filter((id) => id !== claimId)
      : [...current, claimId]);
  }

  return <div className="dialog-backdrop profile-delete-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="profile-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-version-delete-title" onKeyDown={handleKeyDown}>
      <header>
        <span><FileMinus2 size={21} /></span>
        <div><h2 id="profile-version-delete-title">只删除 v{version.versionNumber}“{version.fileName}”</h2><p>其他版本会保留；此版本的原文件、文本与原文依据会被清除。</p></div>
        <button ref={closeRef} type="button" aria-label="关闭版本删除" onClick={onClose}><X size={19} /></button>
      </header>
      <div className="profile-delete-dialog__scroll">
        {busy && !preview ? <div className="profile-delete-dialog__loading" role="status">正在分析这个版本的影响…</div> : null}
        {error ? <p className="profile-delete-dialog__error" role="alert"><AlertTriangle size={16} />{error}</p> : null}
        {preview ? <div className="profile-delete-dialog__body">
          <dl><div><dt>受影响原文</dt><dd>{preview.affectedEvidenceCount}</dd></div><div><dt>受影响简历要点</dt><dd>{preview.affectedClaims.length}</dd></div><div><dt>将失去依据</dt><dd>{preview.unsupportedClaimIds.length}</dd></div></dl>
          {preview.isCurrentVersion ? <label className="profile-version-delete__replacement">
            <span><strong>删除后使用的当前版本</strong><small>当前删除的是正在使用的版本，请选择一个保留版本接替。</small></span>
            <SelectControl aria-label="删除后使用的当前版本" value={replacementVersionId} onChange={(event) => setReplacementVersionId(event.target.value)}>
              {preview.replacementVersions.map((item) => <option key={item.id} value={item.id}>v{item.versionNumber} · {item.fileName}</option>)}
            </SelectControl>
          </label> : null}
          {preview.affectedClaims.length ? <section className="profile-delete-dialog__claims">
            <div className="profile-delete-dialog__claim-toolbar">
              <div><h3>确认简历要点的处理方式</h3><p>先查看内容；可勾选多条后统一处理，再单独调整。</p></div>
              <div className="profile-delete-dialog__claim-batch">
                <label><input type="checkbox" aria-label="全选受影响简历要点" checked={allClaimsSelected} onChange={(event) => setSelectedClaimIds(event.target.checked ? affectedClaims.map((claim) => claim.claimId) : [])} /><span>{allClaimsSelected ? "取消全选" : "全选"}</span></label>
                <span>已选择 {selectedClaims.length} 条</span>
                <SelectControl aria-label="批量更改所选处理方式" value={selectedClaims.length ? bulkChoice : "mixed"} disabled={!selectedClaims.length} onChange={(event) => applyBulkChoice(event.target.value as ClaimDeletionAction)}>
                  <option value="mixed" disabled>批量处理所选</option>
                  <option value="retain_unsupported">所选全部保留</option>
                  <option value="delete">删除所选可删除要点</option>
                </SelectControl>
              </div>
              {selectedProtectedCount ? <small>{selectedProtectedCount} 条仍被其他功能使用，批量删除时会自动保留。</small> : null}
            </div>
            {preview.affectedClaims.map((claim) => {
              const title = claimTitle(claim);
              const expanded = expandedClaimIds.includes(claim.claimId);
              const rows = claimDetailRows(claim);
              return <article key={claim.claimId} className="profile-version-delete__claim" data-selected={selectedClaimIdSet.has(claim.claimId) || undefined}>
                <div className="profile-version-delete__claim-row">
                  <input type="checkbox" aria-label={`选择 ${title}`} checked={selectedClaimIdSet.has(claim.claimId)} onChange={(event) => toggleClaimSelection(claim.claimId, event.target.checked)} />
                  <button type="button" aria-label={`${expanded ? "收起" : "查看"} ${title} 详情`} aria-expanded={expanded} onClick={() => toggleClaimDetails(claim.claimId)}>
                    <span>{profileClaimTypeLabel(claim.claimType)}</span>
                    <strong>{title}</strong>
                    <small>{claim.remainingEvidenceIds.length ? `删除这个版本后，仍有 ${claim.remainingEvidenceIds.length} 条其他依据` : "删除这个版本后，这条要点将没有原文依据"}{claim.selectionIds.length ? "；仍被其他功能使用，不能同时删除" : ""}</small>
                    <ChevronDown size={17} />
                  </button>
                  <SelectControl aria-label={`${title} 的处理方式`} value={choices[claim.claimId]} onChange={(event) => setChoices((value) => ({ ...value, [claim.claimId]: event.target.value as ClaimDeletionAction }))}><option value="retain_unsupported">保留简历要点</option><option value="delete" disabled={Boolean(claim.selectionIds.length)}>同时删除简历要点</option></SelectControl>
                </div>
                {expanded ? <div className="profile-version-delete__claim-detail">
                  {rows.length ? <dl>{rows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl> : <p>这条要点没有更多可展示的字段。</p>}
                  <p>受本版本影响的原文依据 {claim.affectedEvidenceIds.length} 条；其他版本依据 {claim.remainingEvidenceIds.length} 条。</p>
                </div> : null}
              </article>;
            })}
          </section> : null}
          {hasActiveDependency ? <p className="profile-delete-dialog__revoke" role="alert"><AlertTriangle size={17} /><span><strong>这个版本仍被其他功能使用</strong><small>请先解除关联，再删除这个版本。</small></span></p> : null}
        </div> : null}
      </div>
      <footer>
        <div className="profile-delete-dialog__confirm-block">
          <label className="profile-delete-dialog__confirm"><span>输入“{CONFIRM_TEXT}”确认</span><input aria-label={`输入“${CONFIRM_TEXT}”确认`} value={confirmText} onChange={(event) => setConfirmText(event.target.value)} autoComplete="off" /></label>
          {preview && !error ? <span className="profile-delete-dialog__safe"><CheckCircle2 size={14} />预检有效至 {formatBeijingTime(preview.expiresAt, false) ?? preview.expiresAt}</span> : null}
        </div>
        <div className="profile-delete-dialog__actions"><Button variant="ghost" onClick={onClose}>取消，保留版本</Button><Button variant="danger" disabled={!canDelete} loading={busy && Boolean(preview)} onClick={() => void remove()}>删除此版本</Button></div>
      </footer>
    </section>
  </div>;
}
