import { CornerDownLeft, ListChecks } from "lucide-react";
import { FormEvent, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { SessionMessage } from "./SessionMessage";
import type { CurationMessage, CurationSession } from "./reviewTypes";

const recommendationText: Record<string, string> = {
  recommend_confirm: "建议确认",
  suggest_reject: "建议拒绝",
  link_existing: "建议合并",
};

export function CurationConversation({ session, optimisticMessage, busy, onSubmit }: { session: CurationSession | null; optimisticMessage: CurationMessage | null; busy: boolean; onSubmit: (text: string) => void }) {
  const [text, setText] = useState("");
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
    <main className="curation-conversation">
      <header className="curation-conversation__header">
        <div><span>题库整理 Agent</span><h3>{session.title}</h3></div>
        <small>{session.sources.map((source) => source.filename).join("、")}</small>
      </header>
      <div className="curation-conversation__messages" role="log" aria-label="整理对话" aria-live="polite">
        {session.messages.map((message) => <SessionMessage key={message.id} message={message} />)}
        {session.summary.items.length > 0 ? (
          <section className="curation-summary" aria-label="候选题整理总结">
            <div className="review-pane-title"><ListChecks size={17} /><strong>候选题总结</strong><span>v{session.summaryVersion}</span></div>
            {session.summary.items.map((item) => <article key={item.candidateId}><b>{item.ordinal}</b><div><strong>{item.title}</strong><small>{item.topics.join(" / ")} · {item.difficulty} · {item.sourceCount} 个来源</small></div><span>{recommendationText[item.recommendation] ?? item.recommendation}</span></article>)}
          </section>
        ) : null}
        {optimisticMessage ? <SessionMessage message={optimisticMessage} pending /> : null}
      </div>
      <form className="curation-composer" onSubmit={submit}>
        <label htmlFor="curation-command">回复整理 Agent</label>
        <textarea id="curation-command" value={text} disabled={!canCommand || busy} onChange={(event) => setText(event.target.value)} placeholder={canCommand ? "例如：确认全部推荐题；拒绝第 2 题；重写第 4 题：补充边界条件" : "Agent 整理完成后可在这里确认或调整"} />
        <div><small>支持明确的题号指令，含糊命令会先向你澄清。</small><Button type="submit" disabled={!text.trim() || !canCommand || busy} loading={busy}><CornerDownLeft size={16} />发送</Button></div>
      </form>
    </main>
  );
}
