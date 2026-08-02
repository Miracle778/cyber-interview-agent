import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, MessageCircle, RefreshCw, X } from "lucide-react";
import { AgentComposer } from "../../shared/agent/AgentComposer";
import { AgentMessage } from "../../shared/agent/AgentMessage";
import { Button } from "../../shared/ui/Button";
import { decideRetrospectiveCorrection, getRetrospectiveConversation, sendRetrospectiveMessage, stopRetrospectiveMessage } from "./retrospectiveApi";
import type { RetrospectiveCorrectionProposal } from "./retrospectiveTypes";

const proposalLabels: Record<RetrospectiveCorrectionProposal["proposalType"], string> = {
  question_text_correction: "修正问题文字",
  question_segment_rebind: "调整问答片段",
  speaker_correction: "修正说话人",
  analysis_reconsideration: "重新分析这道题",
};

export function RetrospectiveConversation({ workspaceId, retrospectiveId, selectedQuestionId, onClose, onCorrectionConfirmed }: {
  workspaceId: string;
  retrospectiveId: string;
  selectedQuestionId: string | null;
  onClose: () => void;
  onCorrectionConfirmed?: () => void;
}) {
  const [stopping, setStopping] = useState(false);
  const query = useQuery({
    queryKey: ["retrospective-conversation", workspaceId, retrospectiveId],
    queryFn: ({ signal }) => getRetrospectiveConversation(workspaceId, retrospectiveId, signal),
    refetchInterval: (state) => state.state.data?.latestExecution?.status === "running" ? 700 : false,
  });
  const running = query.data?.latestExecution?.status === "running";
  const send = useMutation({ mutationFn: (message: string) => sendRetrospectiveMessage(workspaceId, retrospectiveId, message, selectedQuestionId), onSuccess: () => void query.refetch() });
  const stop = useMutation({
    mutationFn: () => stopRetrospectiveMessage(workspaceId, retrospectiveId, query.data!.latestExecution!.id),
    onMutate: () => setStopping(true),
    onSettled: () => { setStopping(false); void query.refetch(); },
  });
  const decision = useMutation({
    mutationFn: ({ proposalId, value }: { proposalId: string; value: "confirmed" | "rejected" }) => decideRetrospectiveCorrection(workspaceId, retrospectiveId, proposalId, value),
    onSuccess: async (proposal) => { await query.refetch(); if (proposal.status === "confirmed") onCorrectionConfirmed?.(); },
  });
  const proposalsByMessage = useMemo(() => new Map((query.data?.proposals ?? []).filter((item) => item.chatMessageId).map((item) => [item.chatMessageId!, item])), [query.data?.proposals]);
  const lastUserMessage = [...(query.data?.messages ?? [])].reverse().find((item) => item.role === "user")?.content ?? "";
  const failed = query.data?.latestExecution?.status === "failed";
  const latestStatus = query.data?.latestExecution?.status;

  return <aside className="retrospective-conversation" aria-label="复盘讨论与纠正">
    <header><div><span><MessageCircle size={18} /></span><div><h2>讨论与纠正</h2><p>追问分析，或提交一条需要你确认的纠正建议。</p></div></div><button type="button" aria-label="关闭复盘讨论" onClick={onClose}><X size={20} /></button></header>
    <div className="retrospective-conversation__context"><span>{selectedQuestionId ? "当前讨论会优先参考已选中的题目" : "当前讨论整场复盘"}</span>{latestStatus ? <small>本次运行：{latestStatus === "running" ? "处理中" : latestStatus === "completed" ? "已完成" : latestStatus === "cancelled" ? "已停止" : latestStatus === "failed" ? "失败" : latestStatus}</small> : null}</div>
    <div className="retrospective-conversation__messages" aria-live="polite">
      {query.isLoading ? <p className="retrospective-conversation__empty">正在读取讨论记录…</p> : null}
      {!query.isLoading && !(query.data?.messages.length) ? <div className="retrospective-conversation__empty"><MessageCircle size={24} /><strong>可以继续追问这次复盘</strong><p>例如：为什么这道题属于高风险？也可以指出题目、片段或说话人整理有误。</p></div> : null}
      {(query.data?.messages ?? []).map((message) => {
        const proposal = proposalsByMessage.get(message.id);
        if (proposal) return <CorrectionProposal key={message.id} proposal={proposal} busy={decision.isPending} onDecision={(value) => decision.mutate({ proposalId: proposal.id, value })} />;
        return <AgentMessage key={message.id} role={message.role === "user" ? "user" : "assistant"} content={message.content} createdAt={message.createdAt} />;
      })}
      {running ? <AgentMessage role="assistant" content="正在核对当前复盘和已确认资料…" pending /> : null}
      {failed ? <section className="retrospective-conversation__failure" role="alert"><AlertTriangle size={18} /><div><strong>本次讨论没有完成</strong><p>已保留你的问题，可以直接重试。</p></div><Button variant="secondary" onClick={() => send.mutate(lastUserMessage)} disabled={!lastUserMessage || send.isPending}><RefreshCw size={15} />重试</Button></section> : null}
      {send.isError || decision.isError || query.isError ? <p className="retrospective-conversation__error" role="alert">操作没有完成，请稍后重试。</p> : null}
    </div>
    <AgentComposer busy={Boolean(running || send.isPending)} stopping={stopping} modelId="" models={[]} reasoningEffort="none" recipientLabel="复盘助手" placeholder="追问分析，或指出题目、片段、说话人哪里需要纠正…" onModelChange={() => undefined} onReasoningEffortChange={() => undefined} onSend={(message) => send.mutate(message)} onStop={() => stop.mutate()} />
  </aside>;
}

function CorrectionProposal({ proposal, busy, onDecision }: { proposal: RetrospectiveCorrectionProposal; busy: boolean; onDecision: (decision: "confirmed" | "rejected") => void }) {
  return <section className={`retrospective-correction retrospective-correction--${proposal.status}`}>
    <div className="retrospective-correction__title"><span><AlertTriangle size={17} /></span><div><strong>{proposalLabels[proposal.proposalType]}</strong><p>{proposal.rationale}</p></div></div>
    <div className="retrospective-correction__diff"><div><small>当前内容</small><ProposalValue value={proposal.before} /></div><div><small>建议修改为</small><ProposalValue value={proposal.after} /></div></div>
    {proposal.status === "pending" ? <div className="retrospective-correction__actions"><Button variant="secondary" disabled={busy} onClick={() => onDecision("rejected")}>不采用</Button><Button disabled={busy} onClick={() => onDecision("confirmed")}><Check size={16} />确认并重新分析</Button></div> : <p className="retrospective-correction__result">{proposal.status === "confirmed" ? "已确认，新的分析版本正在生成。" : "已拒绝，原分析保持不变。"}</p>}
  </section>;
}

function ProposalValue({ value }: { value: Record<string, unknown> }) {
  const questionText = typeof value.questionText === "string" ? value.questionText : null;
  if (questionText) return <p>{questionText}</p>;
  const segments = Array.isArray(value.segments) ? value.segments : null;
  if (segments) return <ul>{segments.map((item, index) => {
    const row = typeof item === "object" && item ? item as Record<string, unknown> : {};
    return <li key={String(row.segmentId ?? index)}>{String(row.displayName ?? row.speakerRole ?? "片段调整")}</li>;
  })}</ul>;
  const questionSegments = Array.isArray(value.questionSegmentIds) ? value.questionSegmentIds.length : 0;
  const answerSegments = Array.isArray(value.answerSegmentIds) ? value.answerSegmentIds.length : 0;
  if (questionSegments || answerSegments) return <p>问题片段 {questionSegments} 个 · 回答片段 {answerSegments} 个</p>;
  return <p>基于当前分析重新判断</p>;
}
