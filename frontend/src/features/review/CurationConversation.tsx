import { Bot, ChevronDown, FileText, ListChecks, SlidersHorizontal, Square, RotateCcw, XCircle, Rocket, Send } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { SessionMessage } from "./SessionMessage";
import type { CurationMessage, CurationSession, QuestionCandidate } from "./reviewTypes";
import { elapsedSeconds, formatBeijingTime } from "../../shared/time";
import { MarkdownView } from "../knowledge/MarkdownView";
import type { StreamingAssistantState } from "../agent/agentTypes";
import { CurationArtifactCard } from "./CurationArtifactCard";

const recommendationText: Record<string, string> = {
  recommend_confirm: "建议确认",
  suggest_reject: "建议拒绝",
  link_existing: "建议合并",
};

const reasoningEffortLabel = {
  none: "标准",
  low: "较低",
  medium: "中等",
  high: "较高",
} as const;

type TimelineItem = { kind: "message"; message: CurationMessage } | { kind: "process"; id: string; messages: CurationMessage[] };

function groupTimeline(messages: CurationMessage[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  for (const message of messages) {
    const previous = items.at(-1);
    if (message.messageKind === "stage") {
      if (previous?.kind === "process") previous.messages.push(message);
      else items.push({ kind: "process", id: message.id, messages: [message] });
    } else items.push({ kind: "message", message });
  }
  return items;
}

function timeLabel(value: string) {
  return formatBeijingTime(value);
}

function processElapsed(startedAt: string | null | undefined, createdAt: string) {
  if (!startedAt) return null;
  const seconds = elapsedSeconds(startedAt, createdAt);
  if (seconds === null) return null;
  return seconds < 60 ? `+${seconds} 秒` : `+${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function CurationProcessMessage({ messages, startedAt, finishedAt, active, failed }: { messages: CurationMessage[]; startedAt: string | null; finishedAt: string | null; active: boolean; failed: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const timelineRef = useRef<HTMLOListElement>(null);
  const latest = messages.at(-1)!;
  useEffect(() => {
    if (!expanded || !timelineRef.current) return;
    const timeline = timelineRef.current;
    const scrollToLatest = () => { timeline.scrollTop = timeline.scrollHeight; };
    scrollToLatest();
    const frame = globalThis.requestAnimationFrame?.(scrollToLatest);
    return () => { if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame); };
  }, [expanded, messages.length]);
  const processDuration = processElapsed(startedAt, finishedAt ?? latest.createdAt);
  const statusLabel = active ? "Agent 处理中" : failed ? "Agent 处理失败" : "Agent 处理完成";
  return <article className="review-chat-message review-chat-message--agent curation-process-message"><span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span><div className="review-chat-message__content"><div className="review-chat-message__meta"><strong>题匠</strong>{timeLabel(latest.createdAt) ? <span className="review-chat-message__timing"><time dateTime={latest.createdAt}>{timeLabel(latest.createdAt)}</time>{processDuration ? <span>· 耗时 {processDuration.slice(1)}</span> : null}</span> : null}</div><details className="curation-process-card" open={expanded}><summary onClick={(event) => { event.preventDefault(); setExpanded((value) => !value); }}><span>{active ? <i className="status-pulse" /> : null}<strong>{statusLabel}</strong><small>{latest.content}</small></span><em>{messages.length} 条</em><ChevronDown size={16} /></summary><ol ref={timelineRef}>{messages.map((message) => <li key={message.id}><span /><div><p>{message.content}</p><small>{timeLabel(message.createdAt)}{processElapsed(startedAt, message.createdAt) ? ` · ${processElapsed(startedAt, message.createdAt)}` : ""}</small></div></li>)}</ol></details></div></article>;
}

function CurationSummaryCard({ session, candidates, busyId, bulkBusy, bulkRetryAvailable, onBulkPublish, onOpenCandidate, onPublish, onNote }: { session: CurationSession; candidates: Record<string, QuestionCandidate>; busyId: string | null; bulkBusy: boolean; bulkRetryAvailable: boolean; onBulkPublish: () => void; onOpenCandidate: (candidateId: string) => void; onPublish: (candidateId: string) => void; onNote: (candidateId: string, note: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  if (session.summary.items.length === 0) return null;
  const visible = expanded ? session.summary.items : session.summary.items.slice(0, 3);
  return (
    <section className="curation-artifacts" aria-label="已生成文件">
      <header><div><FileText size={16} /><strong>已生成 {session.summary.items.length} 个 Markdown 文件</strong></div><div className="curation-artifacts__header-actions"><span>草稿 v{session.summaryVersion}</span><button type="button" disabled={bulkBusy || (!bulkRetryAvailable && session.pendingCount === 0)} onClick={onBulkPublish}><Rocket size={14} />{bulkRetryAvailable ? "仅重试失败项" : "一键发布"}</button></div></header>
      <div className={`curation-artifacts__list${expanded ? " is-expanded" : ""}`}>
        {visible.map((item) => candidates[item.candidateId] ? <CurationArtifactCard key={item.candidateId} candidate={candidates[item.candidateId]} title={item.title} description={recommendationText[item.recommendation] ?? item.recommendation} busy={busyId === item.candidateId} onOpen={onOpenCandidate} onPublish={onPublish} onSaveNote={onNote} /> : null)}
      </div>
      {session.summary.items.length > 3 ? <button className="curation-artifacts__expand" type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? "收起文件" : `展开其余 ${session.summary.items.length - 3} 个文件`}<ChevronDown size={15} /></button> : null}
    </section>
  );
}

const streamStatusLabel: Record<StreamingAssistantState["status"], string> = {
  running: "Agent 处理中",
  cancelling: "正在停止",
  cancelled: "已停止",
  interrupted: "运行中断",
  failed: "处理失败",
  completed: "处理完成",
};

function StreamingMessage({ state, modelLabel, onRetry, onAbandon }: { state: StreamingAssistantState; modelLabel?: string; onRetry: () => void; onAbandon: () => void }) {
  return <article className={`review-chat-message review-chat-message--agent curation-streaming-message is-${state.status}`}><span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span><div className="review-chat-message__content"><div className="review-chat-message__meta"><strong>题匠</strong><span className="curation-streaming-status">{streamStatusLabel[state.status]}</span>{modelLabel ? <small>{modelLabel}</small> : null}</div><div className="review-chat-message__bubble curation-streaming-message__body">{state.text ? <MarkdownView markdown={state.text} /> : <p>题匠正在理解你的指令</p>}</div>{state.status === "interrupted" ? <div className="curation-recovery-actions"><Button size="sm" onClick={onRetry}><RotateCcw size={14} />重试</Button><Button size="sm" variant="ghost" onClick={onAbandon}><XCircle size={14} />放弃</Button></div> : null}</div></article>;
}

interface CurationConversationProps {
  session: CurationSession | null;
  candidates?: Record<string, QuestionCandidate>;
  optimisticMessage: CurationMessage | null;
  busy: boolean;
  artifactBusyId?: string | null;
  activeExecutionId?: string | null;
  streamingState?: StreamingAssistantState | null;
  models?: { id: string; label: string }[];
  selectedModelId?: string;
  reasoningEffort?: "none" | "low" | "medium" | "high";
  onModelChange?: (modelId: string) => void;
  onReasoningEffortChange?: (effort: "none" | "low" | "medium" | "high") => void;
  onStop?: () => void;
  onRetryCommand?: () => void;
  onAbandonCommand?: () => void;
  onBulkPublish?: () => void;
  bulkBusy?: boolean;
  bulkRetryAvailable?: boolean;
  onSubmit: (text: string) => void;
  onOpenCandidate?: (candidateId: string) => void;
  onPublishCandidate?: (candidateId: string) => void;
  onSaveNote?: (candidateId: string, note: string) => void;
}

export function CurationConversation({ session, candidates = {}, optimisticMessage, busy, artifactBusyId = null, activeExecutionId = null, streamingState = null, models = [], selectedModelId = "", reasoningEffort = "none", onModelChange = () => undefined, onReasoningEffortChange = () => undefined, onStop = () => undefined, onRetryCommand = () => undefined, onAbandonCommand = () => undefined, onBulkPublish = () => undefined, bulkBusy = false, bulkRetryAvailable = false, onSubmit, onOpenCandidate = () => undefined, onPublishCandidate = () => undefined, onSaveNote = () => undefined }: CurationConversationProps) {
  const [text, setText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const timeline = useMemo(() => groupTimeline(session?.messages ?? []), [session?.messages]);
  const summaryAnchor = useMemo(() => {
    for (let index = timeline.length - 1; index >= 0; index -= 1) {
      const item = timeline[index];
      if (item.kind === "message" && item.message.messageKind === "curation_summary") return index;
    }
    return -1;
  }, [timeline]);
  const commandStartedAt = useMemo(() => {
    const result = new Map<string, string>();
    let latestUserTimestamp: string | null = null;
    for (const item of timeline) {
      if (item.kind !== "message") continue;
      const message = item.message;
      if (message.role === "user") {
        latestUserTimestamp = typeof message.payload.submittedAt === "string"
          ? message.payload.submittedAt
          : message.createdAt;
      } else if (message.messageKind === "command_receipt") {
        const startedAt = typeof message.payload.startedAt === "string"
          ? message.payload.startedAt
          : latestUserTimestamp;
        if (startedAt) result.set(message.id, startedAt);
      }
    }
    return result;
  }, [timeline]);
  useEffect(() => {
    const log = logRef.current;
    if (!log || !session) return;
    const scrollToLatest = () => { log.scrollTop = log.scrollHeight; };
    scrollToLatest();
    const frame = globalThis.requestAnimationFrame?.(scrollToLatest);
    return () => { if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame); };
  }, [session?.id, session?.messages.length, session?.summaryVersion, optimisticMessage?.id, streamingState?.text]);
  if (!session) return <main className="curation-conversation curation-conversation--empty"><ListChecks size={28} /><h3>选择或新建整理会话</h3><p>每次整理会保留资料、运行过程、候选题总结和你的确认记录。</p></main>;
  const canCommand = session.stage === "waiting_for_command" || session.stage === "completed";
  const selectedModelLabel = models.find((model) => model.id === selectedModelId)?.label ?? "默认模型";
  function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || !canCommand || busy) return;
    setText("");
    onSubmit(value);
  }
  return (
    <main className="curation-conversation review-conversation review-conversation--chat">
      <h2 className="review-conversation__sr-title">{session.title}</h2>
      <div ref={logRef} className="curation-conversation__messages review-chat-log" role="log" aria-label="整理对话" aria-live="polite">
        {timeline.map((item, index) => <div className="curation-timeline-item" key={item.kind === "process" ? item.id : item.message.id}>{item.kind === "process" ? <CurationProcessMessage messages={item.messages} startedAt={session.executionStartedAt} finishedAt={session.executionFinishedAt} active={!['waiting_for_command', 'completed', 'failed'].includes(session.stage)} failed={session.stage === "failed"} /> : <SessionMessage message={item.message} startedAt={item.message.messageKind === "command_receipt" ? commandStartedAt.get(item.message.id) ?? null : session.executionStartedAt} />}{index === summaryAnchor ? <CurationSummaryCard session={session} candidates={candidates} busyId={artifactBusyId} bulkBusy={bulkBusy} bulkRetryAvailable={bulkRetryAvailable} onBulkPublish={onBulkPublish} onOpenCandidate={onOpenCandidate} onPublish={onPublishCandidate} onNote={onSaveNote} /> : null}</div>)}
        {summaryAnchor < 0 ? <CurationSummaryCard session={session} candidates={candidates} busyId={artifactBusyId} bulkBusy={bulkBusy} bulkRetryAvailable={bulkRetryAvailable} onBulkPublish={onBulkPublish} onOpenCandidate={onOpenCandidate} onPublish={onPublishCandidate} onNote={onSaveNote} /> : null}
        {optimisticMessage ? <SessionMessage message={optimisticMessage} pending startedAt={session.executionStartedAt} /> : null}
        {streamingState && activeExecutionId ? <StreamingMessage state={streamingState} modelLabel={models.find((item) => item.id === selectedModelId)?.label} onRetry={onRetryCommand} onAbandon={onAbandonCommand} /> : null}
      </div>
      <form className="curation-composer review-chat-composer" onSubmit={submit}>
        <label className="review-conversation__sr-title" htmlFor="curation-command">回复题匠</label>
        <div className="review-chat-composer__field">
          <textarea id="curation-command" rows={1} value={text} disabled={!canCommand || busy} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={canCommand ? "输入要求，或直接确认、发布、重写候选题…" : "Agent 整理完成后可在这里确认或调整"} />
          <div className="curation-composer__toolbar">
            <details className="curation-composer__settings">
              <summary aria-disabled={busy} onClick={(event) => { if (busy) event.preventDefault(); }}>
                <SlidersHorizontal size={17} aria-hidden="true" />
                <span>{selectedModelLabel} · {reasoningEffortLabel[reasoningEffort]}</span>
                <ChevronDown size={15} aria-hidden="true" />
              </summary>
              <div className="curation-composer__settings-panel" aria-label="模型与思考强度">
                <label htmlFor="curation-model">本次执行模型</label>
                <select id="curation-model" aria-label="本次执行模型" value={selectedModelId} disabled={busy} onChange={(event) => onModelChange(event.target.value)}><option value="">使用工作区默认模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select>
                <label htmlFor="curation-reasoning">思考强度</label>
                <select id="curation-reasoning" aria-label="思考强度" value={reasoningEffort} disabled={busy} onChange={(event) => onReasoningEffortChange(event.target.value as "none" | "low" | "medium" | "high")}><option value="none">标准</option><option value="low">较低</option><option value="medium">中等</option><option value="high">较高</option></select>
              </div>
            </details>
            <small>Shift+Enter 换行</small>
            <div className="review-chat-composer__actions">
              {busy ? <Button type="button" variant="danger" disabled={streamingState?.status === "cancelling"} onClick={onStop}><Square size={15} />{streamingState?.status === "cancelling" ? "正在停止…" : "停止"}</Button> : <Button className="curation-composer__send" type="submit" aria-label="发送" title="发送" disabled={!text.trim() || !canCommand}><Send size={18} /></Button>}
            </div>
          </div>
        </div>
      </form>
    </main>
  );
}
