import { AlertTriangle, Archive, ArrowRight, Check, FilePlus2, FileText, LoaderCircle, RotateCcw, Trash2, Upload } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { ProfileStatusBadge } from "./ProfileStatusBadge";
import { formatEvidenceLocator } from "./evidenceLocator";
import { isUsefulResumeExcerpt, plainResumeExcerpt } from "./profilePresentation";
import type { ProfileEvidence, ProfileMaterial, ProfileMaterialVersion, ProfileMaterialVersionDetail } from "./profileTypes";

const stageDefinitions = [
  { key: "uploaded", label: "上传" },
  { key: "parsing", label: "提取文本" },
  { key: "parsed", label: "隐私处理" },
  { key: "extracting", label: "生成画像建议" },
  { key: "ready", label: "等待确认" },
];

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function fileTypeLabel(value: string) {
  if (value.includes("pdf")) return "PDF 文件";
  if (value.includes("word") || value.includes("document")) return "Word 文档";
  if (value.includes("markdown")) return "Markdown 文件";
  if (value.includes("text")) return "文本文件";
  return "简历文件";
}

function failureCopy(detail: ProfileMaterialVersionDetail) {
  if (detail.execution?.errorCode?.toLowerCase().includes("model_not_found")) return { title: "尚未配置简历整理模型", action: "配置后重新处理", reason: "简历已经安全保存。请先在设置中绑定简历整理模型，然后从当前版本继续处理，不需要重新上传。" };
  if (detail.processingStatus === "parse_failed") return { title: "文本提取失败", action: "重试文本提取", reason: "未能从文件中读取出稳定文本。原文件和已完成步骤都已保留，重试不会从头上传。" };
  return { title: "简历要点整理失败", action: "重新整理简历要点", reason: "简历要点没有整理完成。已经提取的文本和原文位置都已保留，重试不会重新上传或重新解析简历。" };
}

interface ResumeVersionsProps {
  materials: ProfileMaterial[];
  versions: ProfileMaterialVersion[];
  selectedMaterialId: string | null;
  selectedVersionId: string | null;
  detail: ProfileMaterialVersionDetail | null;
  busy: boolean;
  onSelectMaterial: (materialId: string) => void;
  onSelectVersion: (versionId: string) => void;
  onRetry: (versionId: string) => void;
  onArchive: (material: ProfileMaterial) => void;
  onRestore: (material: ProfileMaterial) => void;
  onSetPrimary: (material: ProfileMaterial, versionId: string) => void;
  onPermanentDelete: (material: ProfileMaterial) => void;
  onOpenEvidence: (evidence: ProfileEvidence) => void;
  onAddVersion: () => void;
}

export function ResumeVersions({ materials, versions, selectedMaterialId, selectedVersionId, detail, busy, onSelectMaterial, onSelectVersion, onRetry, onArchive, onRestore, onSetPrimary, onPermanentDelete, onOpenEvidence, onAddVersion }: ResumeVersionsProps) {
  const material = materials.find((item) => item.id === selectedMaterialId) ?? materials[0] ?? null;
  const selectedIndex = versions.findIndex((item) => item.id === selectedVersionId);
  const failed = detail && (detail.processingStatus === "parse_failed" || detail.processingStatus === "extraction_failed") ? failureCopy(detail) : null;
  const previewItems = detail?.evidencePage.items.filter((item) => isUsefulResumeExcerpt(item.excerpt)).slice(0, 5) ?? [];

  const versionActions = <>
    <dl><div><dt>当前版本</dt><dd>{detail ? `v${detail.versionNumber}` : "—"}</dd></div><div><dt>待确认要点</dt><dd>{detail?.proposalCounts.pending ?? 0}</dd></div><div><dt>原文片段</dt><dd>{detail?.evidencePage.total ?? 0}</dd></div></dl>
    <Button variant="secondary" disabled={!detail || detail.id === material?.currentVersionId || busy} onClick={() => detail && material && onSetPrimary(material, detail.id)}><Check size={16} />设为当前版本</Button>
    {material?.lifecycleStatus === "archived" ? <Button variant="secondary" disabled={busy} onClick={() => onRestore(material)}><RotateCcw size={16} />恢复简历</Button> : <Button variant="ghost" disabled={!material || busy} onClick={() => material && onArchive(material)}><Archive size={16} />归档简历</Button>}
    <div className="profile-version-danger-zone">
      <div><strong>删除整份简历</strong><small>删除前会说明受影响的版本、已确认信息和其他功能引用。</small></div>
      <Button variant="danger" disabled={!material || busy} onClick={() => material && onPermanentDelete(material)}><Trash2 size={16} />永久删除简历</Button>
    </div>
  </>;

  function moveVersion(key: string) {
    if (!versions.length || selectedIndex < 0) return;
    const delta = key === "ArrowDown" || key === "ArrowRight" ? 1 : key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    onSelectVersion(versions[(selectedIndex + delta + versions.length) % versions.length].id);
  }

  const stageProgress = detail ? <ol className="profile-stage-list" aria-label="简历处理进度">{stageDefinitions.map((stage, index) => {
    const backend = detail.stages.find((item) => item.key === stage.key);
    const state = backend?.status ?? (detail.processingStatus === "ready" ? "completed" : "pending");
    return <li key={stage.key} data-state={state}><span>{state === "completed" ? <Check size={15} /> : index + 1}</span><strong>{stage.label}</strong><small>{state === "active" ? "处理中" : state === "failed" ? "未完成" : state === "completed" ? "已完成" : "等待"}</small></li>;
  })}</ol> : null;

  return <section className="profile-versions" aria-labelledby="resume-versions-title">
    <header className="profile-versions__toolbar"><div><h2 id="resume-versions-title">简历与版本</h2><p>查看当前简历、历史版本和系统处理结果。导入新版本不会覆盖旧文件。</p></div><div><Button onClick={onAddVersion}><Upload size={16} />导入新版本简历</Button></div></header>
    <div className="profile-version-workspace">
      <aside className="profile-version-list" aria-label="简历版本列表">
        <div className="profile-material-switcher">{materials.map((item) => <button type="button" key={item.id} aria-pressed={item.id === material?.id} onClick={() => onSelectMaterial(item.id)}>{item.title}<small>{item.lifecycleStatus === "archived" ? "已归档" : `${item.versionCount} 个版本`}</small></button>)}</div>
        <h3>版本历史</h3>
        {versions.map((version) => <button key={version.id} type="button" className="profile-version-row" aria-current={version.id === selectedVersionId} aria-label={`v${version.versionNumber} ${version.fileName}`} onClick={() => onSelectVersion(version.id)} onKeyDown={(event) => moveVersion(event.key)}>
          <FileText size={18} /><span><strong>v{version.versionNumber} {version.fileName}</strong><small>{formatTime(version.createdAt)}</small></span>{version.id === material?.currentVersionId ? <em>当前</em> : null}
        </button>)}
        {!versions.length ? <p className="profile-list-empty">这个材料还没有版本。</p> : null}
      </aside>

      <main className="profile-version-detail">
        {detail ? <>
          <header><FileText size={28} /><div><h2>{detail.fileName} <span>v{detail.versionNumber}</span></h2><p>{fileTypeLabel(detail.mimeType)} · 上传时间 {formatTime(detail.createdAt)}</p></div><ProfileStatusBadge status={detail.processingStatus} lifecycle={detail.material.lifecycleStatus} /></header>
          {detail.processingStatus === "ready"
            ? <details className="profile-stage-details"><summary>这份简历已处理完成 · 查看处理过程</summary>{stageProgress}</details>
            : stageProgress}
          {detail.processingStatus === "extracting" ? <section className="profile-extraction-progress" role="status" aria-label="简历要点整理进度">
            <LoaderCircle size={22} aria-hidden="true" />
            <div>
              <strong>正在整理简历要点</strong>
              <p>已找到 {detail.evidencePage.total} 个原文片段。系统正在整理技能、项目、工作经历、教育经历和个人链接。</p>
              <ol>
                <li data-state="completed"><Check size={14} />提取并处理隐私信息</li>
                <li data-state="active"><LoaderCircle size={14} />整理技能和经历</li>
                <li><span>3</span>关联简历原文并保存</li>
              </ol>
              <small>整理结果需要你确认后才会被简历助手使用。即使中途失败，已经完成的文本处理也不会丢失。</small>
            </div>
          </section> : null}
          {failed ? <div className="profile-stage-error" role="alert"><AlertTriangle size={20} /><div><strong>{failed.title}</strong><p>{failed.reason}</p>{detail.execution?.errorCode ? <small>错误编号：{detail.execution.errorCode}</small> : null}</div><Button variant="secondary" loading={busy} onClick={() => onRetry(detail.id)}><RotateCcw size={16} />{failed.action}</Button></div> : null}
          <section className="profile-document-preview" aria-label="简历内容预览"><header><strong>简历原文（敏感信息已隐藏）</strong><span>{detail.evidencePage.total} 个片段</span></header>{previewItems.length ? previewItems.map((item) => <button key={item.id} type="button" onClick={() => onOpenEvidence(item)}><span><strong>{String(item.locator.block ?? item.locator.section ?? "简历片段")}</strong><small>{formatEvidenceLocator(item.locator)}</small></span><p>{plainResumeExcerpt(item.excerpt)}</p><ArrowRight size={16} /></button>) : <div><FilePlus2 size={24} /><p>{detail.processingStatus === "ready" ? "这份简历暂时没有可展示的文本片段。" : "处理完成后将在这里显示简历原文片段。"}</p></div>}</section>
        </> : <div className="profile-detail-loading" role="status">正在读取版本详情…</div>}
      </main>

      <aside className="profile-version-actions profile-version-actions--desktop" aria-label="版本操作">
        <h3>版本状态</h3>
        {versionActions}
      </aside>
    </div>
  </section>;
}
