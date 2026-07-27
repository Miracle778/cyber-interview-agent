import { AlertTriangle, Eye, FileSearch, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CurationProvisionalCandidate } from "./reviewTypes";

const basisLabels = { source: "基于原资料", mixed: "含 AI 补全", model: "主要由 AI 生成", unknown: "来源依据待确认" } as const;
const supportLabels = { sufficient: "材料充分", partial: "材料部分支持", minimal: "材料支持较少", unknown: "材料支持待确认" } as const;
const statusLabels: Record<string, string> = { pending: "等待处理", running: "正在处理", retryable: "可重试", completed: "已生成", degraded: "已生成，待复核", skipped: "未生成候选", interrupted: "处理已中断" };
const retryableStatuses = new Set(["retryable", "skipped"]);

function generationFailureReason(errorCode?: string | null) {
  const messages: Record<string, string> = {
    missing_candidate: "模型没有返回这道题的完整结果。",
    invalid_candidate: "模型返回的题目格式不完整，未能生成候选题。",
    output_truncated: "模型输出被截断，没有得到完整题目。",
    schema_validation_error: "模型返回的内容格式不符合要求，未能生成题目。",
    protocol_error: "模型返回内容不完整，未能生成题目。",
    provider_timeout: "模型响应超时，本题没有生成。",
    rate_limited: "模型服务当前繁忙，本题没有生成。",
    network_error: "连接模型服务时中断，本题没有生成。",
    provider_server_error: "模型服务暂时异常，本题没有生成。",
    provider_error: "模型调用没有完成，本题没有生成。",
    curation_work_item_failed: "本题处理没有完成，可以单独重试。",
  };
  return errorCode ? messages[errorCode] ?? "本题没有生成有效结果，可以单独重试。" : "本题没有生成有效结果，可以单独重试。";
}

export function CurationProvisionalList({ items, retryingSeedIds = new Set(), onRetry = () => undefined }: { items: CurationProvisionalCandidate[]; retryingSeedIds?: ReadonlySet<string>; onRetry?: (item: CurationProvisionalCandidate) => void }) {
  const [retryableOnly, setRetryableOnly] = useState(false);
  const retryableCount = useMemo(() => items.filter((item) => retryableStatuses.has(item.status ?? "")).length, [items]);
  const visibleItems = retryableOnly ? items.filter((item) => retryableStatuses.has(item.status ?? "")) : items;
  useEffect(() => {
    if (retryableCount === 0) setRetryableOnly(false);
  }, [retryableCount]);
  if (items.length === 0) return null;
  return (
    <section className="curation-provisional" aria-label="处理中候选预览">
      <header>
        <div><Eye size={16} /><strong>处理中预览</strong></div>
        <div className="curation-provisional__filters">
          <button type="button" aria-pressed={!retryableOnly} onClick={() => setRetryableOnly(false)}>全部 {items.length}</button>
          {retryableCount > 0 ? <button type="button" aria-pressed={retryableOnly} onClick={() => setRetryableOnly(true)}>只看待重试 {retryableCount}</button> : null}
        </div>
      </header>
      <p>{retryableCount > 0 ? `有 ${retryableCount} 道题没有生成成功，可筛出后查看原因并单独重试。` : "这里会持续显示已生成和待复核的题目。"}</p>
      <div className="curation-provisional__list" role="list">
        {visibleItems.map((item) => (
          <article key={item.id} role="listitem" className={item.needsReview || ["retryable", "skipped", "degraded"].includes(item.status ?? "") ? "is-warning" : ""}>
            {["retryable", "skipped", "degraded"].includes(item.status ?? "") ? <AlertTriangle size={16} aria-hidden="true" /> : <FileSearch size={16} aria-hidden="true" />}
            <div>
              <strong>{item.title}</strong>
              {item.questionText !== item.title ? <p>{item.questionText}</p> : null}
              {retryableStatuses.has(item.status ?? "") ? <p className="curation-provisional__failure-reason"><b>未生成原因：</b>{generationFailureReason(item.errorCode)}</p> : null}
              <div className="curation-quality-tags" aria-label="候选质量">
                {item.answerBasis && item.answerBasis !== "unknown" ? <span>{basisLabels[item.answerBasis]}</span> : null}
                {item.materialSupport && item.materialSupport !== "unknown" ? <span>{supportLabels[item.materialSupport]}</span> : null}
                {item.needsReview || !item.answerBasis || item.answerBasis === "unknown" || !item.materialSupport || item.materialSupport === "unknown" ? <span>等待质量判断</span> : null}
              </div>
            </div>
            <footer><small>{statusLabels[item.status ?? "completed"] ?? "状态待确认"} · {item.sourceRefs.length} 条证据</small>{item.seedTaskId && retryableStatuses.has(item.status ?? "") ? <button type="button" disabled={retryingSeedIds.has(item.seedTaskId)} onClick={() => onRetry(item)}><RotateCcw size={14} />{retryingSeedIds.has(item.seedTaskId) ? "已接受，处理中" : "重试这一题"}</button> : null}</footer>
          </article>
        ))}
      </div>
    </section>
  );
}
