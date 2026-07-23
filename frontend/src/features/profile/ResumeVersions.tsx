import { AlertTriangle, Archive, ArrowRight, Check, FilePlus2, FileText, RotateCcw, Upload } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { ProfileStatusBadge } from "./ProfileStatusBadge";
import type { ProfileEvidence, ProfileMaterial, ProfileMaterialVersion, ProfileMaterialVersionDetail } from "./profileTypes";

const stageDefinitions = [
  { key: "uploaded", label: "上传" },
  { key: "parsing", label: "文本提取" },
  { key: "parsed", label: "脱敏" },
  { key: "extracting", label: "Claim 提取" },
  { key: "ready", label: "等待审核" },
];

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function failureCopy(detail: ProfileMaterialVersionDetail) {
  if (detail.execution?.errorCode?.toLowerCase().includes("model_not_found")) return { title: "尚未配置画像提取模型", action: "配置后重新处理", reason: "材料已经安全保存。请先在设置中绑定画像提取模型，然后从当前版本继续处理，不需要重新上传。" };
  if (detail.processingStatus === "parse_failed") return { title: "文本提取失败", action: "重试文本提取", reason: "未能从文件中读取出稳定文本。原文件和已完成步骤都已保留，重试不会从头上传。" };
  return { title: "Claim 提取失败", action: "重试 Claim 提取", reason: "结构化提取未完成。已脱敏文本和前序结果都已保留，可从失败阶段继续。" };
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
  onOpenEvidence: (evidence: ProfileEvidence) => void;
  onAddVersion: () => void;
}

export function ResumeVersions({ materials, versions, selectedMaterialId, selectedVersionId, detail, busy, onSelectMaterial, onSelectVersion, onRetry, onArchive, onRestore, onSetPrimary, onOpenEvidence, onAddVersion }: ResumeVersionsProps) {
  const material = materials.find((item) => item.id === selectedMaterialId) ?? materials[0] ?? null;
  const selectedIndex = versions.findIndex((item) => item.id === selectedVersionId);
  const failed = detail && (detail.processingStatus === "parse_failed" || detail.processingStatus === "extraction_failed") ? failureCopy(detail) : null;

  const versionActions = <>
    <dl><div><dt>当前版本</dt><dd>{detail ? `v${detail.versionNumber}` : "—"}</dd></div><div><dt>待确认建议</dt><dd>{detail?.proposalCounts.pending ?? 0}</dd></div><div><dt>证据</dt><dd>{detail?.evidencePage.total ?? 0}</dd></div></dl>
    <Button variant="secondary" disabled={!detail || detail.id === material?.currentVersionId || busy} onClick={() => detail && material && onSetPrimary(material, detail.id)}><Check size={16} />设为当前版本</Button>
    {material?.lifecycleStatus === "archived" ? <Button variant="secondary" disabled={busy} onClick={() => onRestore(material)}><RotateCcw size={16} />恢复材料</Button> : <Button variant="ghost" disabled={!material || busy} onClick={() => material && onArchive(material)}><Archive size={16} />归档材料</Button>}
  </>;

  function moveVersion(key: string) {
    if (!versions.length || selectedIndex < 0) return;
    const delta = key === "ArrowDown" || key === "ArrowRight" ? 1 : key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    onSelectVersion(versions[(selectedIndex + delta + versions.length) % versions.length].id);
  }

  return <section className="profile-versions" aria-labelledby="resume-versions-title">
    <header className="profile-versions__toolbar"><div><h2 id="resume-versions-title">简历版本</h2><p>原文件不可变，修改后的简历作为新版本保留。</p></div><div><Button onClick={onAddVersion}><Upload size={16} />导入新版本简历</Button></div></header>
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
          <header><FileText size={28} /><div><h2>{detail.fileName} <span>v{detail.versionNumber}</span></h2><p>{detail.mimeType} · 上传时间 {formatTime(detail.createdAt)}</p></div><ProfileStatusBadge status={detail.processingStatus} lifecycle={detail.material.lifecycleStatus} /></header>
          <ol className="profile-stage-list" aria-label="材料处理进度">{stageDefinitions.map((stage, index) => {
            const backend = detail.stages.find((item) => item.key === stage.key);
            const state = backend?.status ?? (detail.processingStatus === "ready" ? "completed" : "pending");
            return <li key={stage.key} data-state={state}><span>{state === "completed" ? <Check size={15} /> : index + 1}</span><strong>{stage.label}</strong><small>{state === "active" ? "处理中" : state === "failed" ? "未完成" : state === "completed" ? "已完成" : "等待"}</small></li>;
          })}</ol>
          {failed ? <div className="profile-stage-error" role="alert"><AlertTriangle size={20} /><div><strong>{failed.title}</strong><p>{failed.reason}</p>{detail.execution?.errorCode ? <small>错误编号：{detail.execution.errorCode}</small> : null}</div><Button variant="secondary" loading={busy} onClick={() => onRetry(detail.id)}><RotateCcw size={16} />{failed.action}</Button></div> : null}
          <section className="profile-document-preview" aria-label="材料内容预览"><header><strong>脱敏内容与证据</strong><span>{detail.evidencePage.total} 条</span></header>{detail.evidencePage.items.length ? detail.evidencePage.items.slice(0, 5).map((item) => <button key={item.id} type="button" onClick={() => onOpenEvidence(item)}><span><strong>{String(item.locator.block ?? item.locator.section ?? "材料片段")}</strong><small>{item.locator.page ? `第 ${String(item.locator.page)} 页` : `字符 ${item.startOffset}–${item.endOffset}`}</small></span><p>{item.excerpt}</p><ArrowRight size={16} /></button>) : <div><FilePlus2 size={24} /><p>{detail.processingStatus === "ready" ? "此版本暂无证据片段。" : "处理完成后将在这里显示脱敏文本和证据定位。"}</p></div>}</section>
        </> : <div className="profile-detail-loading" role="status">正在读取版本详情…</div>}
      </main>

      <aside className="profile-version-actions profile-version-actions--desktop" aria-label="版本操作">
        <h3>版本状态</h3>
        {versionActions}
      </aside>
    </div>
  </section>;
}
