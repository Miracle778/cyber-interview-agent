import { AlertTriangle, Eye, FileSearch, RotateCcw } from "lucide-react";
import type { CurationProvisionalCandidate } from "./reviewTypes";

const basisLabels = { source: "基于原资料", mixed: "含 AI 补全", model: "主要由 AI 生成", unknown: "来源依据待确认" } as const;
const supportLabels = { sufficient: "材料充分", partial: "材料部分支持", minimal: "材料支持较少", unknown: "材料支持待确认" } as const;
const statusLabels: Record<string, string> = { pending: "等待处理", running: "正在处理", retryable: "可重试", completed: "已完成", degraded: "已降级保留", skipped: "已跳过", interrupted: "已中断" };

export function CurationProvisionalList({ items, retryingSeedIds = new Set(), onRetry = () => undefined }: { items: CurationProvisionalCandidate[]; retryingSeedIds?: ReadonlySet<string>; onRetry?: (item: CurationProvisionalCandidate) => void }) {
  if (items.length === 0) return null;
  return (
    <section className="curation-provisional" aria-label="处理中候选预览">
      <header>
        <div><Eye size={16} /><strong>处理中预览</strong></div>
        <span>{items.length} 道</span>
      </header>
      <p>这里同时保留处理中、降级和跳过的题目。黄色提示表示需要复核或可以恢复，不代表 Agent 执行失败。</p>
      <div className="curation-provisional__list" role="list">
        {items.map((item) => (
          <article key={item.id} role="listitem" className={item.needsReview || ["retryable", "skipped", "degraded"].includes(item.status ?? "") ? "is-warning" : ""}>
            {["retryable", "skipped", "degraded"].includes(item.status ?? "") ? <AlertTriangle size={16} aria-hidden="true" /> : <FileSearch size={16} aria-hidden="true" />}
            <div>
              <strong>{item.title}</strong>
              <p>{item.questionText}</p>
              <div className="curation-quality-tags" aria-label="候选质量">
                <span>{basisLabels[item.answerBasis ?? "unknown"]}</span>
                <span>{supportLabels[item.materialSupport ?? "unknown"]}</span>
                {item.needsReview ? <span>需要人工复核</span> : null}
              </div>
            </div>
            <footer><small>{statusLabels[item.status ?? "completed"] ?? "状态待确认"} · {item.sourceRefs.length} 条证据</small>{item.seedTaskId && ["retryable", "skipped"].includes(item.status ?? "") ? <button type="button" disabled={retryingSeedIds.has(item.seedTaskId)} onClick={() => onRetry(item)}><RotateCcw size={14} />{retryingSeedIds.has(item.seedTaskId) ? "已接受，处理中" : "重试这一题"}</button> : null}</footer>
          </article>
        ))}
      </div>
    </section>
  );
}
