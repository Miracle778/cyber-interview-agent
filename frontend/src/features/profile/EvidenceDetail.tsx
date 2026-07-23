import { ArrowLeft, FileSearch, LockKeyhole } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ProfileEvidence } from "./profileTypes";
import { formatEvidenceLocator } from "./evidenceLocator";

export function EvidenceDetail({ materialTitle, versionNumber, evidence, onBack }: { materialTitle: string; versionNumber: number; evidence: ProfileEvidence; onBack: () => void }) {
  const block = String(evidence.locator.block ?? evidence.locator.title ?? evidence.locator.section ?? "证据原文");
  return <section className="profile-evidence-detail" aria-labelledby="evidence-title">
    <header className="profile-evidence-detail__header">
      <Button variant="ghost" onClick={onBack} aria-label="返回版本详情"><ArrowLeft size={16} />返回版本</Button>
      <div><span>{materialTitle} · v{versionNumber}</span><h2 id="evidence-title">{block}</h2><p>{formatEvidenceLocator(evidence.locator)}</p></div>
      <span className="profile-evidence-private"><LockKeyhole size={14} />仅自己可见</span>
    </header>
    <div className="profile-evidence-layout">
      <aside className="profile-evidence-outline" aria-label="证据定位">
        <strong>证据定位</strong>
        <dl><div><dt>材料</dt><dd>{materialTitle}</dd></div><div><dt>版本</dt><dd>v{versionNumber}</dd></div><div><dt>位置</dt><dd>{formatEvidenceLocator(evidence.locator)}</dd></div><div><dt>字符范围</dt><dd>{evidence.startOffset}–{evidence.endOffset}</dd></div></dl>
      </aside>
      <article className="profile-evidence-source">
        <div className="profile-evidence-source__toolbar"><FileSearch size={17} /><strong>脱敏后的原文片段</strong></div>
        <blockquote>{evidence.excerpt}</blockquote>
      </article>
      <aside className="profile-evidence-check" aria-label="结构化检查">
        <span>结构化检查</span><h3>{block}</h3>
        <dl><div><dt>来源</dt><dd>{materialTitle} v{versionNumber}</dd></div><div><dt>章节</dt><dd>{formatEvidenceLocator(evidence.locator)}</dd></div><div><dt>可见范围</dt><dd>仅自己可见</dd></div></dl>
        <p>这里只展示脱敏后的证据片段，不会暴露原始文件路径或 Agent 内部参数。</p>
      </aside>
    </div>
  </section>;
}
