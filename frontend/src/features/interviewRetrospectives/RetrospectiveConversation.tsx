import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, BookOpenCheck, Check, MessageCircle, RefreshCw, X } from "lucide-react";
import { AgentComposer } from "../../shared/agent/AgentComposer";
import { AgentMessage } from "../../shared/agent/AgentMessage";
import { AgentProcessCard } from "../../shared/agent/AgentProcessCard";
import { AgentWorkspaceShell } from "../../shared/agent/AgentWorkspaceShell";
import { elapsedSeconds, formatBeijingDateTime, formatElapsedSeconds } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { getAgentSession } from "../agent/agentApi";
import { decideRetrospectiveCorrection, getRetrospectiveConversation, sendRetrospectiveMessage, stopRetrospectiveMessage } from "./retrospectiveApi";
import type { RetrospectiveCorrectionProposal } from "./retrospectiveTypes";

const proposalLabels: Record<RetrospectiveCorrectionProposal["proposalType"], string> = {
  question_text_correction: "修正问题文字",
  question_segment_rebind: "调整问答片段",
  speaker_correction: "修正说话人",
  analysis_reconsideration: "重新分析这道题",
};

const generalStarterPrompts = [
  "总结这次面试最需要改进的三点",
  "哪些结论还缺少原文证据？",
  "帮我把回答整理成更清晰的表达结构",
  "我想纠正一道题或说话人",
];

const questionStarterPrompts = [
  "解释这道题的分析依据",
  "这道题的回答应该突出哪些关键点？",
  "给我一个更清晰的回答结构",
  "这道题还有哪些内容需要补充？",
];

function runtimePresentation(status?: string | null) {
  if (status === "running") return { label: "正在处理", tone: "active" };
  if (status === "cancelling") return { label: "正在停止", tone: "attention" };
  if (status === "waiting_for_input") return { label: "等待你继续", tone: "attention" };
  if (status === "waiting_for_approval") return { label: "等待你确认", tone: "attention" };
  if (status === "failed") return { label: "需要重试", tone: "danger" };
  if (status === "interrupted") return { label: "处理已中断", tone: "stopped" };
  if (status === "cancelled") return { label: "已停止", tone: "stopped" };
  if (status === "completed") return { label: "可继续对话", tone: "ready" };
  return { label: "尚未开始", tone: "idle" };
}

function formatTokens(value: number) {
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

const reasoningLabels = { none: "默认", low: "较少", medium: "适中", high: "深入" } as const;

export function RetrospectiveConversation({ workspaceId, retrospectiveId, selectedQuestionId, selectedQuestionText, onClose, onCorrectionConfirmed }: {
  workspaceId: string;
  retrospectiveId: string;
  selectedQuestionId: string | null;
  selectedQuestionText?: string | null;
  onClose: () => void;
  onCorrectionConfirmed?: () => void;
}) {
  const [stopping, setStopping] = useState(false);
  const [asideOpen, setAsideOpen] = useState(() => globalThis.localStorage?.getItem("retrospective-chat-aside-open") !== "false");
  const [promptToFill, setPromptToFill] = useState<string | null>(null);
  const [following, setFollowing] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const messagesRef = useRef<HTMLDivElement>(null);
  const scrollToBottom = useCallback(() => {
    const messages = messagesRef.current;
    if (!messages) return;
    messages.scrollTop = messages.scrollHeight;
    setFollowing(true);
  }, []);
  const query = useQuery({
    queryKey: ["retrospective-conversation", workspaceId, retrospectiveId],
    queryFn: ({ signal }) => getRetrospectiveConversation(workspaceId, retrospectiveId, signal),
    refetchInterval: (state) => state.state.data?.latestExecution?.status === "running" ? 700 : false,
  });
  const sessionDetail = useQuery({
    queryKey: ["agent-session", query.data?.sessionId],
    queryFn: () => getAgentSession(query.data!.sessionId),
    enabled: Boolean(query.data?.sessionId),
    refetchInterval: ["running", "cancelling"].includes(query.data?.latestExecution?.status ?? "") ? 700 : false,
  });
  const running = ["running", "cancelling"].includes(query.data?.latestExecution?.status ?? "");
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
  const runtime = runtimePresentation(latestStatus);
  const executionStatus = ["running", "cancelling"].includes(latestStatus ?? "") ? "running" : ["waiting_for_input", "waiting_for_approval"].includes(latestStatus ?? "") ? "waiting" : latestStatus === "failed" ? "failed" : ["cancelled", "interrupted"].includes(latestStatus ?? "") ? "stopped" : "completed";
  const executionTitle = executionStatus === "running" ? "复盘助手正在核对资料" : executionStatus === "waiting" ? runtime.label : executionStatus === "failed" ? "本次讨论没有完成" : executionStatus === "stopped" ? "本次讨论已停止" : "本次讨论已完成";
  const messages = query.data?.messages ?? [];
  const latestExecutionId = query.data?.latestExecution?.id ?? null;
  const processBeforeIndex = latestExecutionId ? messages.findIndex((message) => message.executionId === latestExecutionId && message.role === "assistant") : -1;
  const starterPrompts = selectedQuestionId ? questionStarterPrompts : generalStarterPrompts;
  const pendingProposals = (query.data?.proposals ?? []).filter((proposal) => proposal.status === "pending");
  const detailExecution = sessionDetail.data?.latestExecution;
  const durationStart = detailExecution?.startedAt ?? query.data?.latestExecution?.createdAt ?? null;
  const durationFinish = running ? new Date(now).toISOString() : detailExecution?.finishedAt ?? query.data?.latestExecution?.finishedAt ?? durationStart;
  const durationSeconds = durationStart && durationFinish ? elapsedSeconds(durationStart, durationFinish) : null;
  const lastUpdatedAt = detailExecution?.finishedAt ?? detailExecution?.startedAt ?? query.data?.latestExecution?.finishedAt ?? query.data?.latestExecution?.createdAt ?? null;
  const usage = sessionDetail.data?.usage;
  const contextUsage = sessionDetail.data?.contextUsage;
  const updateAside = useCallback((open: boolean) => {
    setAsideOpen(open);
    globalThis.localStorage?.setItem("retrospective-chat-aside-open", String(open));
  }, []);
  useEffect(() => {
    if (following) scrollToBottom();
  }, [following, messages.length, running, scrollToBottom]);
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const interval = globalThis.setInterval(() => setNow(Date.now()), 1000);
    return () => globalThis.clearInterval(interval);
  }, [running]);

  const processCard = query.data?.latestExecution ? <AgentProcessCard
    status={executionStatus}
    title={executionTitle}
    summary={executionStatus === "running" ? "正在读取当前复盘和已确认资料，完成后回答会显示在消息中。" : executionStatus === "waiting" ? (latestStatus === "waiting_for_approval" ? "请先处理本次纠正建议，再继续对话。" : "复盘助手正在等待你的补充信息。") : selectedQuestionId ? "本次回答优先使用已选题目的分析与证据。" : "本次回答基于整场复盘与已授权资料。"}
  >
    {failed ? <Button variant="secondary" onClick={() => send.mutate(lastUserMessage)} disabled={!lastUserMessage || send.isPending}><RefreshCw size={15} />重试本次</Button> : null}
  </AgentProcessCard> : null;

  return <aside className="retrospective-conversation" aria-label="复盘讨论与纠正">
    <AgentWorkspaceShell
      asideOpen={asideOpen}
      onAsideOpenChange={updateAside}
      asideLabel="本次依据"
      header={<div className="retrospective-conversation__header-main"><span><MessageCircle size={18} /></span><div><div className="retrospective-conversation__title-row"><h2>讨论与纠正</h2><span className={`retrospective-conversation__runtime is-${runtime.tone}`} role="status" aria-label={`运行状态：${runtime.label}`}><i aria-hidden="true" />{runtime.label}</span></div><p>与复盘助手追问分析，或提交需要确认的纠正建议。</p></div></div>}
      headerTrailing={<button className="retrospective-conversation__close" type="button" aria-label="关闭复盘讨论" onClick={onClose}><X size={20} /></button>}
      conversation={<div className="retrospective-conversation__main">
        <div className="retrospective-conversation__context"><BookOpenCheck size={15} /><span>{selectedQuestionId ? "当前讨论会优先参考已选中的题目" : "当前讨论整场复盘"}</span></div>
        <div ref={messagesRef} className="retrospective-conversation__messages" role="log" aria-label="复盘助手对话" aria-live="polite" onScroll={(event) => { const target = event.currentTarget; setFollowing(target.scrollHeight - target.scrollTop - target.clientHeight < 72); }}>
          {query.isLoading ? <p className="retrospective-conversation__empty">正在读取讨论记录…</p> : null}
          {!query.isLoading && !messages.length ? <div className="retrospective-conversation__empty"><MessageCircle size={24} /><strong>可以继续追问这次复盘</strong><p>选择一个问题填入输入框，也可以直接指出题目、片段或说话人整理有误。</p><div className="agent-conversation__starters retrospective-conversation__starters">{starterPrompts.map((prompt) => <button key={prompt} type="button" disabled={Boolean(running || send.isPending)} onClick={() => setPromptToFill(prompt)}>{prompt}</button>)}</div></div> : null}
          {messages.map((message, index) => {
            const proposal = proposalsByMessage.get(message.id);
            return <Fragment key={message.id}>{index === processBeforeIndex ? processCard : null}{proposal ? <CorrectionProposal proposal={proposal} busy={decision.isPending} onDecision={(value) => decision.mutate({ proposalId: proposal.id, value })} /> : <AgentMessage role={message.role === "user" ? "user" : "assistant"} content={message.content} createdAt={message.createdAt} assistantLabel="复盘助手" />}</Fragment>;
          })}
          {processBeforeIndex < 0 ? processCard : null}
          {running ? <AgentMessage role="assistant" content="正在核对当前复盘和已确认资料…" pending assistantLabel="复盘助手" /> : null}
          {send.isError || decision.isError || query.isError ? <p className="retrospective-conversation__error" role="alert">操作没有完成，请稍后重试。</p> : null}
        </div>
        {!following ? <button className="agent-conversation__new-message" type="button" onClick={scrollToBottom}><ArrowDown size={15} />有新回复，回到底部</button> : null}
        <AgentComposer busy={Boolean(running || send.isPending)} stopping={stopping} modelId="" models={[]} reasoningEffort="none" recipientLabel="复盘助手" placeholder="追问分析，或指出题目、片段、说话人哪里需要纠正…" promptToFill={promptToFill} onPromptFilled={() => setPromptToFill(null)} onModelChange={() => undefined} onReasoningEffortChange={() => undefined} onSend={(message) => send.mutate(message)} onStop={() => stop.mutate()} />
      </div>}
      aside={<div className="retrospective-conversation__aside">
        <section><h3>本次参考范围</h3><strong>{selectedQuestionText || (selectedQuestionId ? "当前已选题目" : "整场复盘")}</strong><p>读取当前复盘、已授权岗位、已确认画像、题库和已发布知识的有界摘录。</p></section>
        <section className="retrospective-conversation__boundary"><h3>使用边界</h3><p>解释只生成消息；纠正建议需要你确认后才会修改复盘并重新分析。</p></section>
        <section><h3>待你处理</h3>{pendingProposals.length ? <div className="retrospective-conversation__pending"><AlertTriangle size={16} /><span>{pendingProposals.length} 条纠正建议等待确认</span></div> : <div className="retrospective-conversation__aside-empty"><Check size={16} /><span>暂无待确认建议</span></div>}</section>
        <section><h3>运行状态</h3><dl><div><dt>本次状态</dt><dd>{runtime.label}</dd></div><div><dt>本次耗时</dt><dd>{durationSeconds === null ? "尚未运行" : formatElapsedSeconds(durationSeconds)}</dd></div><div><dt>最近更新</dt><dd>{lastUpdatedAt ? formatBeijingDateTime(lastUpdatedAt) ?? "—" : "—"}</dd></div></dl></section>
        <details><summary><span>技术详情</span><small>{usage?.callCount ?? 0} 次调用</small></summary><div className="retrospective-conversation__technical"><dl><div><dt>当前模型</dt><dd title={detailExecution?.configuration?.providerModelId ?? "按工作区默认"}>{detailExecution?.configuration?.providerModelId ?? "按工作区默认"}</dd></div><div><dt>思考强度</dt><dd>{reasoningLabels[detailExecution?.configuration?.reasoningEffort ?? "none"]}</dd></div><div><dt>累计 Token</dt><dd>{formatTokens(usage?.totalTokens ?? 0)}</dd></div><div><dt>上下文</dt><dd>{formatTokens(contextUsage?.currentTokens ?? 0)} / {contextUsage?.thresholdTokens ? formatTokens(contextUsage.thresholdTokens) : "—"}</dd></div></dl><p title={query.data?.sessionId}>会话 ID：{query.data?.sessionId ?? "—"}</p>{query.data?.latestExecution?.id ? <p title={query.data.latestExecution.id}>运行 ID：{query.data.latestExecution.id}</p> : null}{query.data?.latestExecution?.errorCode ? <p className="is-error">错误标识：{query.data.latestExecution.errorCode}</p> : null}</div></details>
      </div>}
    />
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
