import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, X } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { permanentlyDeleteMaterial, previewMaterialDeletion } from "./profileApi";
import type { MaterialDeletionPreview, PermanentMaterialDeletionResult, ProfileMaterial } from "./profileTypes";

const CONFIRM_TEXT = "永久删除";

export function DeletionImpactDialog({ open, workspaceId, material, onClose, onDeleted }: { open: boolean; workspaceId: string; material: ProfileMaterial; onClose: () => void; onDeleted: (result: PermanentMaterialDeletionResult) => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [preview, setPreview] = useState<MaterialDeletionPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, "delete" | "retain_unsupported">>({});
  const [confirmText, setConfirmText] = useState("");
  const [revoke, setRevoke] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setPreview(null); setChoices({}); setConfirmText(""); setRevoke(false); setError(null); setBusy(true);
    void previewMaterialDeletion(workspaceId, material).then((result) => {
      setPreview(result);
      setChoices(Object.fromEntries(result.affectedClaims.map((claim) => [claim.claimId, "retain_unsupported"])));
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "删除影响读取失败")).finally(() => setBusy(false));
    queueMicrotask(() => closeRef.current?.focus());
    return () => returnFocusRef.current?.focus();
  }, [open, workspaceId, material.id, material.version]);

  if (!open) return null;

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled])') ?? [])];
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  async function remove() {
    if (!preview) return;
    setBusy(true); setError(null);
    try {
      const result = await permanentlyDeleteMaterial(workspaceId, material, preview, Object.entries(choices).map(([claimId, action]) => ({ claimId, action })), preview.activePublicationIds.length ? "revoke" : "not_applicable");
      onDeleted(result);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "永久删除没有完成"); }
    finally { setBusy(false); }
  }

  const requiresRevoke = Boolean(preview?.activePublicationIds.length);
  const protectedDelete = preview?.affectedClaims.some((claim) => claim.selectionIds.length && choices[claim.claimId] === "delete");
  const canDelete = Boolean(preview && confirmText === CONFIRM_TEXT && (!requiresRevoke || revoke) && !protectedDelete);

  return <div className="dialog-backdrop profile-delete-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="profile-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-delete-title" onKeyDown={handleKeyDown}>
      <header><span><ShieldAlert size={21} /></span><div><h2 id="profile-delete-title">永久删除“{material.title}”</h2><p>归档可恢复；永久删除会清除原文件和证据正文，此操作不可撤销。</p></div><button ref={closeRef} type="button" aria-label="关闭永久删除" onClick={onClose}><X size={19} /></button></header>
      {busy && !preview ? <div className="profile-delete-dialog__loading" role="status">正在分析材料依赖…</div> : null}
      {error ? <p className="profile-delete-dialog__error" role="alert"><AlertTriangle size={16} />{error}</p> : null}
      {preview ? <div className="profile-delete-dialog__body">
        <dl><div><dt>受影响证据</dt><dd>{preview.affectedEvidenceCount}</dd></div><div><dt>受影响画像</dt><dd>{preview.affectedClaims.length}</dd></div><div><dt>将失去依据</dt><dd>{preview.unsupportedClaimIds.length}</dd></div><div><dt>活动发布</dt><dd>{preview.activePublicationIds.length}</dd></div></dl>
        {preview.affectedClaims.length ? <section><h3>逐条选择画像处理方式</h3>{preview.affectedClaims.map((claim) => <label key={claim.claimId}><span><strong>{claim.claimType}</strong><small>{claim.remainingEvidenceIds.length ? `仍有 ${claim.remainingEvidenceIds.length} 条其他证据` : "删除材料后将没有证据支持"}{claim.selectionIds.length ? "；已用于发布选择，不能直接删除" : ""}</small></span><select aria-label={`${claim.claimType} 的处理方式`} value={choices[claim.claimId]} onChange={(event) => setChoices((value) => ({ ...value, [claim.claimId]: event.target.value as "delete" | "retain_unsupported" }))}><option value="retain_unsupported">保留并标记为依据不足</option><option value="delete" disabled={Boolean(claim.selectionIds.length)}>同时删除画像项</option></select></label>)}</section> : null}
        {requiresRevoke ? <label className="profile-delete-dialog__revoke"><input type="checkbox" checked={revoke} onChange={(event) => setRevoke(event.target.checked)} /><span><strong>同时撤销已发布的个人知识</strong><small>必须先撤销 {preview.activePublicationIds.length} 个活动发布，才能继续删除。</small></span></label> : null}
        <label className="profile-delete-dialog__confirm"><span>输入“{CONFIRM_TEXT}”确认</span><input value={confirmText} onChange={(event) => setConfirmText(event.target.value)} autoComplete="off" /></label>
      </div> : null}
      <footer><Button variant="ghost" onClick={onClose}>取消，保留材料</Button><Button variant="danger" disabled={!canDelete} loading={busy && Boolean(preview)} onClick={() => void remove()}>永久删除</Button></footer>
      {preview && !error ? <span className="profile-delete-dialog__safe"><CheckCircle2 size={14} />预检有效至 {new Date(preview.expiresAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span> : null}
    </section>
  </div>;
}
