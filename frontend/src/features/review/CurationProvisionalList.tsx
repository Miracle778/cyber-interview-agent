import { Eye, FileSearch } from "lucide-react";
import type { CurationProvisionalCandidate } from "./reviewTypes";

export function CurationProvisionalList({ items }: { items: CurationProvisionalCandidate[] }) {
  if (items.length === 0) return null;
  return (
    <section className="curation-provisional" aria-label="处理中候选预览">
      <header>
        <div><Eye size={16} /><strong>处理中预览</strong></div>
        <span>{items.length} 道</span>
      </header>
      <p>这些结果仍在归并中，仅供查看；完成后才会生成可确认的正式候选。</p>
      <div className="curation-provisional__list" role="list">
        {items.map((item) => (
          <article key={item.id} role="listitem">
            <FileSearch size={16} aria-hidden="true" />
            <div>
              <strong>{item.title}</strong>
              <p>{item.questionText}</p>
            </div>
            <small>{item.sourceRefs.length} 条证据</small>
          </article>
        ))}
      </div>
    </section>
  );
}
