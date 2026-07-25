import { AlertTriangle, Eye, FileSearch, RotateCcw } from "lucide-react";
import type { CurationProvisionalCandidate } from "./reviewTypes";

const basisLabels = { source: "基于原资料", mixed: "含 AI 补全", model: "主要由 AI 生成", unknown: "来源依据待确认" } as const;
const supportLabels = { sufficient: "材料充分", partial: "材料部分支持", minimal: "材料支持较少", unknown: "材料支持待确认" } as const;
const statusLabels: Record<string, string> = { pending: "等待处理", running: "正在处理", retryable: "可重试", completed: "已生成", degraded: "已生成，待复核", skipped: "未生成候选", interrupted: "处理已中断" };

export function CurationProvisionalList({ items, retryingSeedIds = new Set(), onRetry = () => undefined }: { items: CurationProvisionalCandidate[]; retryingSeedIds?: ReadonlySet<string>; onRetry?: (item: CurationProvisionalCandidate) => void }) {
  if (items.length === 0) return null;
  return (
    <section className="curation-provisional" aria-label="处理中候选预览">
      <header>
        <div><Eye size={16} /><strong>处理中预览</strong></div>
        <span>{items.length} 道</span>
      </header>
      <p>这里会持续显示已生成、待复核和可以重试的题目。黄色提示表示需要你检查，不代表 Agent 执行失败。</p>
      <div className="curation-provisional__list" role="list">
        {items.map((item) => (
          <article key={item.id} role="listitem" className={item.needsReview || ["retryable", "skipped", "degraded"].includes(item.status ?? "") ? "is-warning" : ""}>
            {["retryable", "skipped", "degraded"].includes(item.status ?? "") ? <AlertTriangle size={16} aria-hidden="true" /> : <FileSearch size={16} aria-hidden="true" />}
            <div>
              <strong>{item.title}</strong>
              {item.questionText !== item.title ? <p>{item.questionText}</p> : null}
              <div className="curation-quality-tags" aria-label="候选质量">
                {item.answerBasis && item.answerBasis !== "unknown" ? <span>{basisLabels[item.answerBasis]}</span> : null}
                {item.materialSupport && item.materialSupport !== "unknown" ? <span>{supportLabels[item.materialSupport]}</span> : null}
                {item.needsReview || !item.answerBasis || item.answerBasis === "unknown" || !item.materialSupport || item.materialSupport === "unknown" ? <span>等待质量判断</span> : null}
              </div>
            </div>
            <footer><small>{statusLabels[item.status ?? "completed"] ?? "状态待确认"} · {item.sourceRefs.length} 条证据</small>{item.seedTaskId && ["retryable", "skipped"].includes(item.status ?? "") ? <button type="button" disabled={retryingSeedIds.has(item.seedTaskId)} onClick={() => onRetry(item)}><RotateCcw size={14} />{retryingSeedIds.has(item.seedTaskId) ? "已接受，处理中" : "重试这一题"}</button> : null}</footer>
          </article>
        ))}
      </div>
    </section>
  );
}
