import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, Bot, Check, ChevronDown, Copy, MessageSquareText, RotateCcw, Send, SlidersHorizontal, Square, TriangleAlert } from "lucide-react";
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { cancelAgentExecution, getAgentSession, startAgentExecution } from "../agent/agentApi";
import { useAgentEvents } from "../agent/useAgentEvents";
import { listProviders } from "../settings/settingsApi";
import { Button } from "../../shared/ui/Button";
import { elapsedSeconds } from "../../shared/time";
import { ReviewChatMessage } from "./ReviewConversation";
import { retryReviewDiscussion } from "./reviewApi";
import type { ReviewAttempt, ReviewTimelineMessage } from "./reviewTypes";

const suggestions = ["解释我遗漏的关键点", "结合我的回答给一个实际案例", "换一种更容易记住的方式说明"];
type ReasoningEffort = "none" | "low" | "medium" | "high";
const reasoningLabels: Record<ReasoningEffort, string> = { none: "标准", low: "较低", medium: "中等", high: "较高" };

function formatDuration(startedAt?: string | null, finishedAt?: string | null, now = Date.now()) {
  if (!startedAt) return "尚未运行";
  const start = Date.parse(startedAt);
  const end = finishedAt ? Date.parse(finishedAt) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function formatTokens(value: number) {
  const precision = value >= 100_000 ? 1 : 2;
  return `${(value / 1000).toFixed(precision).replace(/\.0+$|(?<=\.[0-9])0+$/, "")}k`;
}

export function ReviewDiscussion({ roundId, sessionId, attempt, defaultModelId, defaultReasoning = "none", onClose }: { roundId: string; sessionId: string; attempt: ReviewAttempt; defaultModelId?: string; defaultReasoning?: ReasoningEffort; onClose: () => void }) {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState(defaultModelId ?? "");
  const [reasoning, setReasoning] = useState<ReasoningEffort>(defaultReasoning);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [openContext, setOpenContext] = useState<"question" | "evaluation" | null>("question");
  const [now, setNow] = useState(Date.now());
  const logRef = useRef<HTMLDivElement>(null);
  const session = useQuery({ queryKey: ["agent-session", sessionId], queryFn: () => getAgentSession(sessionId) });
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const stream = useAgentEvents(sessionId);
  const refresh = () => client.invalidateQueries({ queryKey: ["agent-session", sessionId] });
  const send = useMutation({
    mutationFn: (value: string) => startAgentExecution(sessionId, { message: value }, { providerModelId: selectedModel || null, reasoningEffort: reasoning }),
    onSuccess: async () => { setMessage(""); await refresh(); setPendingUserMessage(null); },
    onError: () => setPendingUserMessage(null),
  });
  const stop = useMutation({ mutationFn: (executionId: string) => cancelAgentExecution(executionId), onSuccess: refresh });
  const retry = useMutation({ mutationFn: () => retryReviewDiscussion(roundId, sessionId), onSuccess: refresh });
  useEffect(() => { if (stream.events.length) void refresh(); }, [stream.events.length, sessionId]);
  const durable: ReviewTimelineMessage[] = (session.data?.messages ?? []).filter((item) => ["user", "assistant"].includes(item.role)).map((item) => ({ ...item, messageKind: "discussion", payload: {} }));
  const executionId = session.data?.latestExecution?.id ?? session.data?.latestExecutionId;
  const streamed = executionId ? stream.streamingByExecution[executionId] : undefined;
  const liveStatus = executionId ? stream.executionStateById[executionId] : undefined;
  const executionStatus = liveStatus ?? session.data?.latestExecution?.status;
  const hasDurableResponse = durable.some((item) => item.executionId === executionId && item.role === "assistant");
  const streamingMessage: ReviewTimelineMessage | null = streamed?.text && !hasDurableResponse ? { id: `stream-${executionId}`, executionId: executionId ?? null, role: "assistant", content: streamed.text, messageKind: "discussion", payload: {}, createdAt: new Date().toISOString() } : null;
  const optimisticMessage: ReviewTimelineMessage | null = pendingUserMessage ? { id: "pending-discussion-user", executionId: null, role: "user", content: pendingUserMessage, messageKind: "discussion", payload: {}, createdAt: new Date().toISOString() } : null;
  const running = send.isPending || (!hasDurableResponse && (["running", "cancelling"].includes(executionStatus ?? "") || streamed?.status === "running"));
  const failed = executionStatus === "failed" || Boolean(stream.executionError);
  const models = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled ? provider.models.filter((model) => model.enabled).map((model) => ({ id: model.id, label: `${provider.name} / ${model.displayName}` })) : []), [providers.data]);
  const effectiveModel = selectedModel || session.data?.latestExecution?.configuration?.providerModelId || defaultModelId || "";
  const effectiveReasoning = reasoning || session.data?.latestExecution?.configuration?.reasoningEffort || defaultReasoning;
  const selectedModelLabel = models.find((model) => model.id === effectiveModel)?.label ?? "当前绑定模型";
  const currentContextTokens = session.data?.contextUsage?.currentTokens ?? 0;
  const contextThresholdTokens = session.data?.contextUsage?.thresholdTokens ?? 0;
  const contextPercentage = contextThresholdTokens > 0 ? Math.min(100, Math.round((currentContextTokens / contextThresholdTokens) * 100)) : 0;
  const statusLabel = running ? "回复中" : failed ? "回复失败" : executionStatus === "cancelled" ? "已停止" : durable.length ? "讨论中" : "待提问";
  const executionById = new Map((session.data?.executions ?? []).map((item) => [item.id, item]));
  const messageProcessingSeconds = (item: ReviewTimelineMessage) => {
    if (item.role !== "assistant" || !item.executionId) return null;
    const execution = executionById.get(item.executionId);
    if (!execution?.startedAt) return null;
    const finishedAt = execution.finishedAt ?? (item.id.startsWith("stream-") ? new Date(now).toISOString() : item.createdAt);
    return elapsedSeconds(execution.startedAt, finishedAt);
  };
  useEffect(() => { const log = logRef.current; if (log) log.scrollTop = log.scrollHeight; }, [durable.length, streamingMessage?.content, optimisticMessage?.content]);
  useEffect(() => { if (!running) return; const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, [running]);

  async function submit() {
    const value = message.trim();
    if (!value || running) return;
    setPendingUserMessage(value);
    await send.mutateAsync(value);
  }

  async function copyMessage(item: ReviewTimelineMessage) {
    await navigator.clipboard.writeText(item.content);
    setCopiedId(item.id);
    window.setTimeout(() => setCopiedId((current) => current === item.id ? null : current), 1500);
  }

  return <section className="review-discussion" aria-label="深入讨论会话">
    <header className="review-discussion__header">
      <div className="review-discussion__title"><span>单题深入讨论</span><h2>{session.data?.title ?? `深入讨论：${attempt.questionSnapshot.title}`}</h2></div>
      <div className="review-discussion__header-actions">
        <Button variant="ghost" size="sm" onClick={onClose}><ArrowLeft size={16} />返回复习报告</Button>
        <span className={`review-discussion__status${running ? " is-running" : failed ? " is-failed" : ""}`}><span className="status-pulse" />{statusLabel}</span>
      </div>
    </header>
    <div className="review-discussion__workspace">
      <div className="review-discussion__conversation">
        <div ref={logRef} className="review-chat-log" role="log" aria-label="深入讨论记录" aria-live="polite">
          {!durable.length && !optimisticMessage ? <div className="review-discussion__empty"><Bot size={20} /><div><strong>本题上下文已准备好</strong><p>选择建议问题或自由追问；只有发送后才会调用复习助手。</p></div></div> : null}
          {durable.map((item) => <div key={item.id} className="review-discussion__message"> <ReviewChatMessage message={item} processingSeconds={messageProcessingSeconds(item)} />{item.role === "assistant" ? <button type="button" className="review-discussion__copy" aria-label="复制这条回复" onClick={() => void copyMessage(item)}>{copiedId === item.id ? <Check size={14} /> : <Copy size={14} />}{copiedId === item.id ? "已复制" : "复制"}</button> : null}</div>)}
          {optimisticMessage ? <ReviewChatMessage message={optimisticMessage} pending /> : null}
          {streamingMessage ? <ReviewChatMessage message={streamingMessage} pending={streamed?.status === "running"} processingSeconds={messageProcessingSeconds(streamingMessage)} /> : null}
          {running && !streamingMessage ? <div className="review-typing-row" role="status"><span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span><div className="review-typing-indicator"><span className="status-pulse" />复习助手正在整理思路…</div></div> : null}
          {failed ? <div className="review-discussion__error" role="alert"><span>本次回复失败，问题和上下文均已保留。</span><Button size="sm" variant="ghost" loading={retry.isPending} onClick={() => retry.mutate()}><RotateCcw size={14} />重试本次回复</Button></div> : null}
        </div>
        <form className="curation-composer review-chat-composer review-discussion__composer" onSubmit={(event) => { event.preventDefault(); void submit().catch(() => undefined); }}>
          <div className="review-discussion__suggestions" aria-label="建议问题">{suggestions.map((item) => <button key={item} type="button" disabled={running} onClick={() => setMessage(item)}>{item}</button>)}</div>
          <label className="review-conversation__sr-title" htmlFor="review-discussion-message">继续追问</label>
          <div className="review-chat-composer__field"><textarea id="review-discussion-message" rows={1} value={message} disabled={running} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="继续追问遗漏点、案例或换一种解释方式…" /><div className="curation-composer__toolbar"><details className="curation-composer__settings"><summary aria-disabled={running} onClick={(event) => { if (running) event.preventDefault(); }}><SlidersHorizontal size={17} aria-hidden="true" /><span>{selectedModelLabel} · {reasoningLabels[effectiveReasoning]}</span><ChevronDown size={15} aria-hidden="true" /></summary><div className="curation-composer__settings-panel" aria-label="模型与思考强度"><label htmlFor="review-discussion-model">本次执行模型</label><select id="review-discussion-model" aria-label="讨论模型" value={effectiveModel} disabled={running} onChange={(event) => setSelectedModel(event.target.value)}>{!effectiveModel ? <option value="">请选择模型</option> : null}{effectiveModel && !models.some((model) => model.id === effectiveModel) ? <option value={effectiveModel}>当前绑定模型</option> : null}{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select><label htmlFor="review-discussion-reasoning">思考强度</label><select id="review-discussion-reasoning" aria-label="思考强度" value={effectiveReasoning} disabled={running} onChange={(event) => setReasoning(event.target.value as ReasoningEffort)}>{Object.entries(reasoningLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div></details><small>Shift+Enter 换行</small><div className="review-chat-composer__actions">{running && executionId ? <Button type="button" variant="danger" disabled={stop.isPending} onClick={() => stop.mutate(executionId)}><Square size={15} />{stop.isPending ? "正在停止…" : "停止"}</Button> : <Button className="curation-composer__send" type="submit" aria-label="发送" title="发送" disabled={!message.trim() || !effectiveModel} loading={send.isPending}><Send size={18} /></Button>}</div></div></div>
        </form>
      </div>
      <aside className="review-discussion__aside" aria-label="本题讨论上下文">
        <div className="review-discussion__aside-title"><MessageSquareText size={17} /><strong>运行状态</strong><span>{statusLabel}</span></div>
        <details className="curation-runtime-disclosure review-discussion__runtime" open><summary><span><Activity size={16} />运行详情</span><small>{session.data?.usage.callCount ?? 0} 次调用</small><ChevronDown size={16} /></summary><div className="curation-runtime-disclosure__body"><dl><div><dt>执行状态</dt><dd>{statusLabel}</dd></div><div><dt>本次耗时</dt><dd>{formatDuration(session.data?.latestExecution?.startedAt, running ? null : session.data?.latestExecution?.finishedAt, now)}</dd></div><div><dt>执行模型</dt><dd title={selectedModelLabel}>{selectedModelLabel}</dd></div><div><dt>Token</dt><dd>{formatTokens(session.data?.usage.totalTokens ?? 0)}</dd></div></dl><div className="curation-context-compact"><div className="curation-context-ring" style={{ "--context-progress": `${contextPercentage * 3.6}deg` } as CSSProperties}><span>{contextPercentage}%</span></div><div><small>当前上下文 / 压缩阈值</small><strong>{formatTokens(currentContextTokens)} / {contextThresholdTokens > 0 ? formatTokens(contextThresholdTokens) : "—"}</strong>{session.data?.contextCompacted ? <em>已执行上下文压缩</em> : null}</div></div></div></details>
        {session.data?.latestWarning ? <details className="curation-runtime-warning" open><summary><TriangleAlert size={16} />提示 <span>1</span></summary><p>{session.data.latestWarning.message}</p></details> : null}
        <details className="review-discussion__context" open={openContext === "question"}><summary onClick={(event) => { event.preventDefault(); setOpenContext((value) => value === "question" ? null : "question"); }}>本题上下文</summary><div><small>题目</small><strong>{attempt.questionSnapshot.questionText}</strong></div><div><small>你的回答</small><p>{attempt.answer || "本题未填写回答"}</p></div>{attempt.followUpAnswer ? <div><small>补充回答</small><p>{attempt.followUpAnswer}</p></div> : null}</details>
        {attempt.evaluation ? <details className="review-discussion__context review-discussion__evaluation" open={openContext === "evaluation"}><summary onClick={(event) => { event.preventDefault(); setOpenContext((value) => value === "evaluation" ? null : "evaluation"); }}>评价摘要</summary><div><p>{attempt.evaluation.evidence}</p>{attempt.evaluation.missing_key_points?.length ? <ul>{attempt.evaluation.missing_key_points.map((point, index) => <li key={`${index}:${point}`}>{point}</li>)}</ul> : null}</div></details> : null}
      </aside>
    </div>
  </section>;
}
