import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Archive, ArrowRight, Check, FilePlus2, FileText, MoreHorizontal, RotateCcw, Trash2, Upload } from "lucide-react";
import { formatBeijingDateTime } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import { ProfileStatusBadge } from "./ProfileStatusBadge";
import { formatEvidencePosition, formatEvidenceTitle } from "./evidenceLocator";
import { isUsefulResumeExcerpt, plainResumeExcerpt } from "./profilePresentation";
import type { ProfileEvidence, ProfileMaterial, ProfileMaterialVersion, ProfileMaterialVersionDetail } from "./profileTypes";

const stageDefinitions = [
  { key: "uploaded", label: "上传文件" },
  { key: "parsing", label: "提取文本" },
  { key: "parsed", label: "隐私处理" },
  { key: "extracting", label: "生成画像建议" },
  { key: "ready", label: "生成确认清单" },
];

function formatTime(value: string) {
  return formatBeijingDateTime(value) ?? value;
}

function fileTypeLabel(value: string) {
  if (value.includes("pdf")) return "PDF 文件";
  if (value.includes("word") || value.includes("document")) return "Word 文档";
  if (value.includes("markdown")) return "Markdown 文件";
  if (value.includes("text")) return "文本文件";
  return "简历文件";
}

function failureCopy(detail: ProfileMaterialVersionDetail) {
  if (detail.execution?.errorCode?.toLowerCase().includes("model_not_found")) return { title: "尚未配置简历整理模型", action: "配置后继续整理", reason: "简历已经安全保存。绑定模型后可从当前阶段继续，不需要重新上传。" };
  if (detail.processingStatus === "parse_failed") return { title: "文本提取失败", action: "继续提取文本", reason: "原文件已保留，继续时不会重新上传。" };
  return { title: "画像建议整理未完成", action: "继续整理画像建议", reason: "已提取文本和内容区块均已保留，不会从头开始。" };
}

interface ResumeVersionsProps {
  materials: ProfileMaterial[];
  versions: ProfileMaterialVersion[];
  selectedMaterialId: string | null;
  selectedVersionId: string | null;
  detail: ProfileMaterialVersionDetail | null;
  pendingProposalCount?: number | null;
  busy: boolean;
  onSelectMaterial: (materialId: string) => void;
  onSelectVersion: (versionId: string) => void;
  onRetry: (versionId: string) => void;
  onArchive: (material: ProfileMaterial) => void;
  onRestore: (material: ProfileMaterial) => void;
  onSetPrimary: (material: ProfileMaterial, versionId: string) => void;
  onPermanentDelete: (material: ProfileMaterial) => void;
  onPermanentDeleteVersion: (material: ProfileMaterial, version: ProfileMaterialVersionDetail) => void;
  onOpenEvidence?: (evidence: ProfileEvidence) => void;
  onOpenDocument?: (evidenceId?: string) => void;
  onAddVersion: () => void;
  processFocusRequest?: number;
}

export function ResumeVersions({ materials, versions, selectedMaterialId, selectedVersionId, detail, pendingProposalCount, busy, onSelectMaterial, onSelectVersion, onRetry, onArchive, onRestore, onSetPrimary, onPermanentDelete, onPermanentDeleteVersion, onOpenEvidence, onOpenDocument, onAddVersion, processFocusRequest = 0 }: ResumeVersionsProps) {
  const material = materials.find((item) => item.id === selectedMaterialId) ?? materials[0] ?? null;
  const selectedIndex = versions.findIndex((item) => item.id === selectedVersionId);
  const failed = detail && (detail.processingStatus === "parse_failed" || detail.processingStatus === "extraction_failed") ? failureCopy(detail) : null;
  const previewItems = (detail?.evidencePage.items.filter((item) => isUsefulResumeExcerpt(item.excerpt)) ?? []).slice(0, 4);
  const processPanelRef = useRef<HTMLElement>(null);
  const [processHighlighted, setProcessHighlighted] = useState(false);
  const effectivePendingProposalCount = pendingProposalCount === undefined
    ? (detail?.proposalCounts.pending ?? 0)
    : (pendingProposalCount ?? 0);
  const versionDeleteReason = pendingProposalCount === null
    ? "正在核对待确认信息，暂时不能删除简历版本"
    : effectivePendingProposalCount > 0
      ? `请先处理全部 ${effectivePendingProposalCount} 条待确认信息，再删除任一简历版本`
      : versions.length <= 1
    ? "这是唯一版本，如需清除请删除整份简历"
      : null;

  useEffect(() => {
    if (!processFocusRequest || !detail) return;
    const frame = window.requestAnimationFrame(() => {
      const panel = processPanelRef.current;
      if (!panel) return;
      panel.scrollIntoView?.({ behavior: "smooth", block: "center" });
      panel.focus({ preventScroll: true });
      setProcessHighlighted(true);
    });
    const timer = window.setTimeout(() => setProcessHighlighted(false), 1800);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [detail?.id, processFocusRequest]);

  function openDocument(evidenceId?: string) {
    if (onOpenDocument) return onOpenDocument(evidenceId);
    const evidence = detail?.evidencePage.items.find((item) => item.id === evidenceId);
    if (evidence && onOpenEvidence) onOpenEvidence(evidence);
  }

  function moveVersion(key: string) {
    if (!versions.length || selectedIndex < 0) return;
    const delta = key === "ArrowDown" || key === "ArrowRight" ? 1 : key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    onSelectVersion(versions[(selectedIndex + delta + versions.length) % versions.length].id);
  }

  const stageProgress = detail ? <ol className="profile-stage-list" aria-label="简历处理进度">{stageDefinitions.map((stage, index) => {
    const backend = detail.stages.find((item) => item.key === stage.key);
    const state = backend?.status ?? (detail.processingStatus === "ready" ? "completed" : "pending");
    return <li key={stage.key} data-state={state}><span>{state === "completed" ? <Check size={15} /> : index + 1}</span><strong>{stage.label}</strong><small>{state === "active" ? "正在处理" : state === "failed" ? "未完成" : state === "completed" ? "已完成" : "等待"}</small></li>;
  })}</ol> : null;

  return <TaskWorkspace className="profile-versions" labelledBy="resume-versions-title">
    <header className="profile-versions__toolbar">
      <div><h2 id="resume-versions-title">简历与来源</h2><p>管理简历版本、查看完整内容，并了解画像建议的处理过程。</p></div>
      <Button onClick={onAddVersion}><Upload size={16} />导入新版本</Button>
    </header>
    <div className="profile-version-workspace">
      <TaskWorkspacePane className="profile-version-list" aria-label="简历版本列表">
        <div className="profile-material-switcher">{materials.map((item) => <button type="button" key={item.id} aria-pressed={item.id === material?.id} onClick={() => onSelectMaterial(item.id)}><span>{item.title}</span><small>{item.lifecycleStatus === "archived" ? "已归档" : `${item.versionCount} 个版本`}</small></button>)}</div>
        <h3>版本历史</h3>
        {versions.map((version) => <button key={version.id} type="button" className="profile-version-row" aria-current={version.id === selectedVersionId} aria-label={`v${version.versionNumber} ${version.fileName}`} onClick={() => onSelectVersion(version.id)} onKeyDown={(event) => moveVersion(event.key)}>
          <FileText size={18} /><span><strong>v{version.versionNumber} {version.fileName}</strong><small>{formatTime(version.createdAt)}</small></span>{version.id === material?.currentVersionId ? <em>当前</em> : null}
        </button>)}
        {!versions.length ? <p className="profile-list-empty">这个材料还没有版本。</p> : null}
      </TaskWorkspacePane>

      <section className="profile-version-detail">
        {detail ? <>
          <header className="profile-version-detail__header">
            <FileText size={26} />
            <div className="profile-version-detail__identity"><h2>{detail.fileName} <span>v{detail.versionNumber}</span></h2><p>{fileTypeLabel(detail.mimeType)} · 上传时间 {formatTime(detail.createdAt)}</p></div>
            <dl className="profile-version-metrics">
              <div><dt>待确认</dt><dd>{detail.proposalCounts.pending}</dd></div>
              <div><dt>内容区块</dt><dd>{detail.evidencePage.total}</dd></div>
            </dl>
            <ProfileStatusBadge status={detail.processingStatus} lifecycle={detail.material.lifecycleStatus} pendingCount={detail.proposalCounts.pending} />
            <details className="profile-version-menu">
              <summary aria-label="版本操作"><MoreHorizontal size={20} /></summary>
              <div>
                <Button variant="ghost" disabled={detail.id === material?.currentVersionId || busy} onClick={() => material && onSetPrimary(material, detail.id)}><Check size={16} />设为当前版本</Button>
                {material?.lifecycleStatus === "archived"
                  ? <Button variant="ghost" disabled={busy} onClick={() => material && onRestore(material)}><RotateCcw size={16} />恢复简历</Button>
                  : <Button variant="ghost" disabled={!material || busy} onClick={() => material && onArchive(material)}><Archive size={16} />归档简历</Button>}
                <Button variant="danger" disabled={!material || busy || Boolean(versionDeleteReason)} onClick={() => material && onPermanentDeleteVersion(material, detail)}><Trash2 size={16} />删除当前版本 v{detail.versionNumber}</Button>
                {versionDeleteReason ? <small className="profile-version-menu__hint">{versionDeleteReason}</small> : null}
                <Button variant="danger" disabled={!material || busy} onClick={() => material && onPermanentDelete(material)}><Trash2 size={16} />永久删除整份简历（含 {versions.length} 个版本）</Button>
              </div>
            </details>
          </header>

          <TaskWorkspacePane className="profile-version-detail__scroll">
            <section
              ref={processPanelRef}
              className="profile-process-panel"
              aria-label="简历处理过程"
              data-highlighted={processHighlighted}
              tabIndex={-1}
            >
              {detail.processingStatus === "ready"
                ? <details className="profile-stage-details"><summary>已处理完成 · 查看处理过程</summary>{stageProgress}</details>
                : stageProgress}
              {detail.processingStatus === "extracting" ? <section className="profile-processing-explanation" role="status">
                <strong>正在根据 {detail.evidencePage.total} 个内容区块整理画像建议</strong>
                <p>当前正在识别技能、项目、工作经历、教育经历和成果。停止后会保留文件、文本和已完成步骤。</p>
              </section> : null}
              {failed ? <div className="profile-stage-error" role="alert"><AlertTriangle size={20} /><div><strong>{failed.title}</strong><p>{failed.reason}</p></div><Button variant="secondary" loading={busy} onClick={() => onRetry(detail.id)}><RotateCcw size={16} />{failed.action}</Button></div> : null}
            </section>

            <section className="profile-document-entry">
              <div><FileText size={22} /><span><strong>完整简历</strong><small>查看本地原文，或切换到模型使用的脱敏版本。</small></span></div>
              <Button variant="secondary" onClick={() => openDocument()}>查看完整简历<ArrowRight size={16} /></Button>
            </section>

            <section className="profile-document-preview" aria-label="简历内容预览">
              <header><strong>内容定位</strong><span>显示 {previewItems.length} / {detail.evidencePage.total} 个区块</span></header>
              {previewItems.length ? previewItems.map((item) => <button key={item.id} type="button" onClick={() => openDocument(item.id)}>
                <span><strong>{formatEvidenceTitle(item.locator)}</strong><small>{formatEvidencePosition(item.locator) || "简历中的位置"}</small></span><p>{plainResumeExcerpt(item.excerpt)}</p><ArrowRight size={16} />
              </button>) : <div><FilePlus2 size={24} /><p>{detail.processingStatus === "ready" ? "这份简历暂时没有可展示的内容。" : "处理完成后将在这里显示内容定位。"}</p></div>}
            </section>
          </TaskWorkspacePane>
        </> : <div className="profile-detail-loading" role="status">正在读取版本详情…</div>}
      </section>
    </div>
  </TaskWorkspace>;
}
