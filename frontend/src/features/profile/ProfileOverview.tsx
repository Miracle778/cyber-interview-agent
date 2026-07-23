import { ArrowRight, BriefcaseBusiness, Check, FileText, LockKeyhole, Upload } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { ProfileStatusBadge } from "./ProfileStatusBadge";
import type { ProfileMaterial, ProfileMaterialVersionDetail } from "./profileTypes";

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function ProfileOverview({ material, detail, onImport, onOpenVersions, onOpenEvidence }: { material: ProfileMaterial; detail: ProfileMaterialVersionDetail | null; onImport: () => void; onOpenVersions: () => void; onOpenEvidence: (evidenceId: string) => void }) {
  const evidence = detail?.evidencePage.items ?? [];
  const pending = detail?.proposalCounts.pending ?? 0;
  const processingFailed = detail?.processingStatus.endsWith("_failed") ?? false;
  return <div className="profile-overview">
    <section className="profile-current-material" aria-labelledby="current-material-title">
      <div><span>当前主简历</span><h2 id="current-material-title">{material.title} v{detail?.versionNumber ?? material.versionCount}</h2><p>最后更新时间：{formatDate(material.updatedAt)}</p></div>
      <div className="profile-current-material__actions"><ProfileStatusBadge status={detail?.processingStatus ?? material.latestProcessingStatus} lifecycle={material.lifecycleStatus} /><Button onClick={onImport}><Upload size={16} />导入新版本简历</Button></div>
    </section>

    <div className="profile-overview-grid">
      <main className="profile-overview-main">
        <section className="profile-source-strip" aria-label="个人材料来源">
          <button type="button" onClick={onOpenVersions}><FileText size={23} /><span><strong>v{detail?.versionNumber ?? material.versionCount} {material.title}</strong><small>{formatDate(material.updatedAt)} · 当前使用</small></span><ArrowRight size={16} /></button>
          <button type="button" onClick={onOpenVersions}><BriefcaseBusiness size={23} /><span><strong>材料版本</strong><small>共 {material.versionCount} 个版本 · 可追溯</small></span><ArrowRight size={16} /></button>
        </section>

        <section className="profile-confirmed-card" aria-labelledby="confirmed-profile-title">
          <header><div><span>已提取资料</span><h2 id="confirmed-profile-title">证据与经历线索</h2></div><span>证据 {detail?.evidencePage.total ?? 0} 条</span></header>
          {evidence.length ? <div className="profile-evidence-preview-list">{evidence.slice(0, 4).map((item) => <button type="button" key={item.id} onClick={() => onOpenEvidence(item.id)}><div><strong>{String(item.locator.block ?? item.locator.section ?? "材料片段")}</strong><p>{item.excerpt}</p></div><span>{item.locator.page ? `第 ${String(item.locator.page)} 页` : "查看定位"}<ArrowRight size={15} /></span></button>)}</div> : <div className="profile-inline-empty"><FileText size={22} /><div><strong>{processingFailed ? "材料处理未完成" : detail?.processingStatus === "ready" ? "暂无可展示的证据" : "材料正在处理中"}</strong><p>{processingFailed ? "原文件和已完成步骤都已保留，请到简历版本查看原因并重试。" : detail?.processingStatus === "ready" ? "后续确认的画像会在这里按来源归档。" : "完成文本提取和脱敏后，会在这里显示可追溯片段。"}</p>{processingFailed ? <button className="profile-inline-link" type="button" onClick={onOpenVersions}>查看处理详情</button> : null}</div></div>}
        </section>

        <section className="profile-privacy-card"><span><LockKeyhole size={19} /></span><div><strong>知识库可用 {detail?.proposalCounts.accepted ?? 0} 项 / 仅自己可见 {detail?.proposalCounts.total ?? 0} 项</strong><p>个人材料默认保持私有，只有明确确认并发布的内容才会进入面试问答。</p></div><Button variant="secondary" disabled>管理发布范围</Button></section>
      </main>

      <aside className="profile-suggestion-panel" aria-labelledby="profile-suggestion-title">
        <header><h2 id="profile-suggestion-title">待确认建议 <span>{pending}</span></h2><Button size="sm" variant="secondary" disabled={pending === 0}>进入审阅</Button></header>
        {pending ? <div className="profile-suggestion-list"><article><span>材料提取</span><h3>有 {pending} 项画像建议等待确认</h3><p>建议来自当前简历的脱敏文本，确认前不会改变正式画像。</p><footer><button type="button" onClick={onOpenVersions}>查看依据</button><button type="button" disabled><Check size={14} />确认</button></footer></article></div> : <div className="profile-suggestion-empty"><Check size={22} /><strong>暂无待确认建议</strong><p>新材料处理完成后，建议会出现在这里。</p></div>}
      </aside>
    </div>
  </div>;
}
