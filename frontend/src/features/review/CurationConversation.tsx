import { Bot, Check, ChevronDown, CornerDownLeft, Eye, FileText, MessageSquareText, Send, ListChecks } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { SessionMessage } from "./SessionMessage";
import type { CurationMessage, CurationSession, QuestionCandidate } from "./reviewTypes";
import { elapsedSeconds, formatBeijingTime } from "../../shared/time";

const recommendationText: Record<string, string> = {
  recommend_confirm: "建议确认",
  suggest_reject: "建议拒绝",
  link_existing: "建议合并",
};

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

function CurationSummaryCard({ session, candidates, busyId, onOpenCandidate, onPublish, onNote }: { session: CurationSession; candidates: Record<string, QuestionCandidate>; busyId: string | null; onOpenCandidate: (candidateId: string) => void; onPublish: (candidateId: string) => void; onNote: (candidateId: string, note: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [notingId, setNotingId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  if (session.summary.items.length === 0) return null;
  const visible = expanded ? session.summary.items : session.summary.items.slice(0, 3);
  return (
    <section className="curation-artifacts" aria-label="已生成文件">
      <header><div><FileText size={16} /><strong>已生成 {session.summary.items.length} 个 Markdown 文件</strong></div><span>草稿 v{session.summaryVersion}</span></header>
      <div className={`curation-artifacts__list${expanded ? " is-expanded" : ""}`}>
        {visible.map((item) => { const candidate = candidates[item.candidateId]; const published = candidate?.status === "published"; return <article key={item.candidateId} className={published ? "is-published" : ""}><span className="curation-artifacts__file"><FileText size={16} /></span><div><strong title={`${item.title}.md`}>{item.title}.md</strong><small>{recommendationText[item.recommendation] ?? item.recommendation}{candidate?.reviewNote ? " · 已备注" : ""}</small></div><em>{published ? <><Check size={13} />已发布</> : "草稿"}</em><div className="curation-artifacts__actions"><button type="button" onClick={() => onOpenCandidate(item.candidateId)}><Eye size={14} />查看</button><button type="button" disabled={published || busyId === item.candidateId} onClick={() => onPublish(item.candidateId)}><Send size={14} />{published ? "已发布" : "发布"}</button><button type="button" onClick={() => { setNotingId(item.candidateId); setNote(candidate?.reviewNote ?? ""); }}><MessageSquareText size={14} />备注</button></div></article>; })}
      </div>
      {session.summary.items.length > 3 ? <button className="curation-artifacts__expand" type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? "收起文件" : `展开其余 ${session.summary.items.length - 3} 个文件`}<ChevronDown size={15} /></button> : null}
      {notingId ? <div className="curation-note-editor"><label htmlFor="candidate-note">修改备注</label><textarea id="candidate-note" autoFocus value={note} onChange={(event) => setNote(event.target.value)} placeholder="写下修改意见；保存后不会立即重新生成" /><small>保存备注只记录意见。稍后可在会话中让 Agent 按备注重新生成。</small><div><button type="button" onClick={() => setNotingId(null)}>取消</button><Button type="button" disabled={busyId === notingId} loading={busyId === notingId} onClick={() => { onNote(notingId, note); setNotingId(null); }}>保存备注</Button></div></div> : null}
    </section>
  );
}

export function CurationConversation({ session, candidates = {}, optimisticMessage, busy, artifactBusyId = null, onSubmit, onOpenCandidate = () => undefined, onPublishCandidate = () => undefined, onSaveNote = () => undefined }: { session: CurationSession | null; candidates?: Record<string, QuestionCandidate>; optimisticMessage: CurationMessage | null; busy: boolean; artifactBusyId?: string | null; onSubmit: (text: string) => void; onOpenCandidate?: (candidateId: string) => void; onPublishCandidate?: (candidateId: string) => void; onSaveNote?: (candidateId: string, note: string) => void }) {
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
  }, [session?.id, session?.messages.length, session?.summaryVersion, optimisticMessage?.id]);
  if (!session) return <main className="curation-conversation curation-conversation--empty"><ListChecks size={28} /><h3>选择或新建整理会话</h3><p>每次整理会保留资料、运行过程、候选题总结和你的确认记录。</p></main>;
  const canCommand = session.stage === "waiting_for_command" || session.stage === "completed";
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
        {timeline.map((item, index) => <div className="curation-timeline-item" key={item.kind === "process" ? item.id : item.message.id}>{item.kind === "process" ? <CurationProcessMessage messages={item.messages} startedAt={session.executionStartedAt} finishedAt={session.executionFinishedAt} active={!['waiting_for_command', 'completed', 'failed'].includes(session.stage)} failed={session.stage === "failed"} /> : <SessionMessage message={item.message} startedAt={item.message.messageKind === "command_receipt" ? commandStartedAt.get(item.message.id) ?? null : session.executionStartedAt} />}{index === summaryAnchor ? <CurationSummaryCard session={session} candidates={candidates} busyId={artifactBusyId} onOpenCandidate={onOpenCandidate} onPublish={onPublishCandidate} onNote={onSaveNote} /> : null}</div>)}
        {summaryAnchor < 0 ? <CurationSummaryCard session={session} candidates={candidates} busyId={artifactBusyId} onOpenCandidate={onOpenCandidate} onPublish={onPublishCandidate} onNote={onSaveNote} /> : null}
        {optimisticMessage ? <SessionMessage message={optimisticMessage} pending startedAt={session.executionStartedAt} /> : null}
      </div>
      <form className="curation-composer review-chat-composer" onSubmit={submit}>
        <label htmlFor="curation-command">回复题匠</label>
        <div className="review-chat-composer__field"><textarea id="curation-command" value={text} disabled={!canCommand || busy} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={canCommand ? "自由描述你的要求，例如：按备注重新生成，其他推荐题直接发布" : "Agent 整理完成后可在这里确认或调整"} /><div className="review-chat-composer__actions"><small>Enter 发送 · Shift+Enter 换行</small><Button type="submit" disabled={!text.trim() || !canCommand || busy} loading={busy}><CornerDownLeft size={16} />发送</Button></div></div>
      </form>
    </main>
  );
}
