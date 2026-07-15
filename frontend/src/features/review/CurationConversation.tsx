import { Bot, ChevronDown, CornerDownLeft, ListChecks } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { SessionMessage } from "./SessionMessage";
import type { CurationMessage, CurationSession } from "./reviewTypes";

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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function processElapsed(startedAt: string | null | undefined, createdAt: string) {
  const start = new Date(startedAt ?? "").getTime();
  const end = new Date(createdAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  const seconds = Math.round((end - start) / 1000);
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

function CurationSummaryCard({ session, onOpenCandidate }: { session: CurationSession; onOpenCandidate: (candidateId: string) => void }) {
  if (session.summary.items.length === 0) return null;
  return (
    <section className="curation-summary" aria-label="候选题整理总结">
      <header><div><ListChecks size={16} /><strong>候选题总结</strong></div><span>{session.summary.items.length} 题 · v{session.summaryVersion}</span></header>
      <div className="curation-summary__list">
        {session.summary.items.map((item) => <article key={item.candidateId}><b>{item.ordinal}</b><div><strong title={item.title}>{item.title}</strong><small>{item.topics.join(" / ")} · {item.difficulty} · {item.sourceCount} 个来源</small></div><span>{recommendationText[item.recommendation] ?? item.recommendation}</span><button type="button" onClick={() => onOpenCandidate(item.candidateId)}>查看编辑</button></article>)}
      </div>
    </section>
  );
}

export function CurationConversation({ session, optimisticMessage, busy, onSubmit, onOpenCandidate = () => undefined }: { session: CurationSession | null; optimisticMessage: CurationMessage | null; busy: boolean; onSubmit: (text: string) => void; onOpenCandidate?: (candidateId: string) => void }) {
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
        {timeline.map((item, index) => <div className="curation-timeline-item" key={item.kind === "process" ? item.id : item.message.id}>{item.kind === "process" ? <CurationProcessMessage messages={item.messages} startedAt={session.executionStartedAt} finishedAt={session.executionFinishedAt} active={!['waiting_for_command', 'completed', 'failed'].includes(session.stage)} failed={session.stage === "failed"} /> : <SessionMessage message={item.message} startedAt={session.executionStartedAt} />}{index === summaryAnchor ? <CurationSummaryCard session={session} onOpenCandidate={onOpenCandidate} /> : null}</div>)}
        {summaryAnchor < 0 ? <CurationSummaryCard session={session} onOpenCandidate={onOpenCandidate} /> : null}
        {optimisticMessage ? <SessionMessage message={optimisticMessage} pending startedAt={session.executionStartedAt} /> : null}
      </div>
      <form className="curation-composer review-chat-composer" onSubmit={submit}>
        <label htmlFor="curation-command">回复题匠</label>
        <div className="review-chat-composer__field"><textarea id="curation-command" value={text} disabled={!canCommand || busy} onChange={(event) => setText(event.target.value)} placeholder={canCommand ? "例如：确认全部推荐题；拒绝第 2 题；重写第 4 题：补充边界条件" : "Agent 整理完成后可在这里确认或调整"} /><div className="review-chat-composer__actions"><small>明确题号指令</small><Button type="submit" disabled={!text.trim() || !canCommand || busy} loading={busy}><CornerDownLeft size={16} />发送</Button></div></div>
      </form>
    </main>
  );
}
