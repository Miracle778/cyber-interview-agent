import { ArrowRight, BriefcaseBusiness, Check, FileText, LockKeyhole, Upload } from "lucide-react";
import { formatBeijingDate } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { formatEvidencePosition, formatEvidenceTitle } from "./evidenceLocator";
import { ProfileStatusBadge } from "./ProfileStatusBadge";
import { isUsefulResumeExcerpt, plainResumeExcerpt } from "./profilePresentation";
import type { ProfileMaterial, ProfileMaterialVersionDetail } from "./profileTypes";

function formatDate(value: string) {
  return formatBeijingDate(value) ?? value;
}

export function ProfileOverview({ material, detail, onImport, onOpenVersions, onOpenClaims, onOpenEvidence }: { material: ProfileMaterial; detail: ProfileMaterialVersionDetail | null; onImport: () => void; onOpenVersions: () => void; onOpenClaims: () => void; onOpenEvidence: (evidenceId: string) => void }) {
  const evidence = detail?.evidencePage.items ?? [];
  const usefulEvidence = evidence.filter((item) => isUsefulResumeExcerpt(item.excerpt));
  const pending = detail?.proposalCounts.pending ?? 0;
  const processingFailed = detail?.processingStatus.endsWith("_failed") ?? false;
  return <div className="profile-overview">
    <section className="profile-current-material" aria-labelledby="current-material-title">
      <div><span>当前使用的简历</span><h2 id="current-material-title">{material.title} v{detail?.versionNumber ?? material.versionCount}</h2><p>最后更新时间：{formatDate(material.updatedAt)}</p></div>
      <div className="profile-current-material__actions"><ProfileStatusBadge status={detail?.processingStatus ?? material.latestProcessingStatus} lifecycle={material.lifecycleStatus} pendingCount={detail?.proposalCounts.pending} /><Button onClick={onImport}><Upload size={16} />导入新版本简历</Button></div>
    </section>

    <div className="profile-overview-grid">
      <main className="profile-overview-main">
        <section className="profile-source-strip" aria-label="个人材料来源">
          <button type="button" onClick={onOpenVersions}><FileText size={23} /><span><strong>v{detail?.versionNumber ?? material.versionCount} {material.title}</strong><small>{formatDate(material.updatedAt)} · 当前使用</small></span><ArrowRight size={16} /></button>
          <button type="button" onClick={onOpenVersions}><BriefcaseBusiness size={23} /><span><strong>版本历史</strong><small>共 {material.versionCount} 个版本 · 可随时切换</small></span><ArrowRight size={16} /></button>
        </section>

        <section className="profile-confirmed-card" aria-labelledby="confirmed-profile-title">
          <header><div><span>内容预览</span><h2 id="confirmed-profile-title">简历中的主要内容</h2></div><span>显示 {Math.min(usefulEvidence.length, 4)} / {detail?.evidencePage.total ?? 0} 个内容区块</span></header>
          {usefulEvidence.length ? <div className="profile-evidence-preview-list">{usefulEvidence.slice(0, 4).map((item) => <button type="button" key={item.id} onClick={() => onOpenEvidence(item.id)}><div><strong>{formatEvidenceTitle(item.locator)}</strong><p>{plainResumeExcerpt(item.excerpt)}</p></div><span>{formatEvidencePosition(item.locator) || "查看完整内容"}<ArrowRight size={15} /></span></button>)}</div> : <div className="profile-inline-empty"><FileText size={22} /><div><strong>{processingFailed ? "简历处理未完成" : detail?.processingStatus === "ready" ? "暂时没有可展示的信息" : "正在整理简历"}</strong><p>{processingFailed ? "原文件和已完成步骤都已保留，请到简历与版本查看原因并重试。" : detail?.processingStatus === "ready" ? "导入内容更完整的简历后，系统会继续整理。" : "处理完成后，你可以确认哪些信息准确。"}</p>{processingFailed ? <button className="profile-inline-link" type="button" onClick={onOpenVersions}>查看处理详情</button> : null}</div></div>}
        </section>

        <section className="profile-privacy-card"><span><LockKeyhole size={19} /></span><div><strong>只有确认过的信息才会用于后续准备</strong><p>创建求职目标后，系统会按你选择的岗位和资料范围进行分析；待确认、已拒绝和敏感信息不会自动使用。</p></div></section>
      </main>

      <aside className="profile-suggestion-panel" aria-labelledby="profile-suggestion-title">
        <header><h2 id="profile-suggestion-title">下一步 <span>{pending}</span></h2><Button size="sm" variant="secondary" disabled={pending === 0} onClick={onOpenClaims}>开始确认</Button></header>
        {pending ? <div className="profile-suggestion-list"><article><span>大约 2–5 分钟</span><h3>确认 {pending} 条简历要点</h3><p>系统从简历中整理出了技能和经历。确认后，简历助手才能更准确地回答关于你的问题。</p><footer><button type="button" onClick={onOpenVersions}>先看简历原文</button><button type="button" onClick={onOpenClaims}><Check size={14} />开始确认</button></footer></article></div> : <div className="profile-suggestion-empty"><Check size={22} /><strong>当前没有需要确认的内容</strong><p>你可以直接使用简历助手，或导入更新的简历。</p></div>}
      </aside>
    </div>
  </div>;
}
