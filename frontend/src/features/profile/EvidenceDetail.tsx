import { ArrowLeft, FileSearch, LockKeyhole } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ProfileEvidence } from "./profileTypes";
import { formatEvidenceLocator } from "./evidenceLocator";

export function EvidenceDetail({ materialTitle, versionNumber, evidence, onBack }: { materialTitle: string; versionNumber: number; evidence: ProfileEvidence; onBack: () => void }) {
  const block = String(evidence.locator.block ?? evidence.locator.title ?? evidence.locator.section ?? "简历原文");
  return <section className="profile-evidence-detail" aria-labelledby="evidence-title">
    <header className="profile-evidence-detail__header">
      <Button variant="ghost" onClick={onBack} aria-label="返回版本详情"><ArrowLeft size={16} />返回版本</Button>
      <div><span>{materialTitle} · v{versionNumber}</span><h2 id="evidence-title">{block}</h2><p>{formatEvidenceLocator(evidence.locator)}</p></div>
      <span className="profile-evidence-private"><LockKeyhole size={14} />仅自己可见</span>
    </header>
    <div className="profile-evidence-layout">
      <aside className="profile-evidence-outline" aria-label="原文位置">
        <strong>原文位置</strong>
        <dl><div><dt>简历</dt><dd>{materialTitle}</dd></div><div><dt>版本</dt><dd>v{versionNumber}</dd></div><div><dt>位置</dt><dd>{formatEvidenceLocator(evidence.locator)}</dd></div></dl>
      </aside>
      <article className="profile-evidence-source">
        <div className="profile-evidence-source__toolbar"><FileSearch size={17} /><strong>简历原文（敏感信息已隐藏）</strong></div>
        <blockquote>{evidence.excerpt}</blockquote>
      </article>
      <aside className="profile-evidence-check" aria-label="隐私说明">
        <span>隐私说明</span><h3>这段内容如何使用</h3>
        <dl><div><dt>来源</dt><dd>{materialTitle} v{versionNumber}</dd></div><div><dt>用于</dt><dd>帮助你核对简历要点</dd></div><div><dt>可见范围</dt><dd>仅自己可见</dd></div></dl>
        <p>系统会把这段原文作为核对依据；只有确认过的信息才会提供给后续岗位分析和面试训练。</p>
      </aside>
    </div>
  </section>;
}
