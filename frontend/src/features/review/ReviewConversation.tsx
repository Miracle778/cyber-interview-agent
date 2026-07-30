import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Bot, Check, ChevronDown, Send, SkipForward, SlidersHorizontal, RotateCcw, Square, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { ReviewRound, ReviewTimelineMessage } from "./reviewTypes";
import { elapsedSeconds, formatBeijingTime, formatElapsedSeconds } from "../../shared/time";
import { listProviders } from "../settings/settingsApi";
import { useAgentComposerKeyboard } from "../../shared/agent/useAgentComposerKeyboard";
import { CurrentQuestionCard } from "./CurrentQuestionCard";

type ReasoningEffort = "none" | "low" | "medium" | "high";
type ReviewAnswerConfiguration = { providerModelId: string; reasoningEffort: ReasoningEffort };
export type ReviewEvaluationStage = "preparing" | "checking_key_points" | "deciding_follow_up";

const evaluationStages = [
  { key: "saved", label: "回答已保存", detail: "刷新或评价失败后仍会保留" },
  { key: "preparing", label: "理解本次回答", detail: "识别回答范围与当前题意" },
  { key: "checking_key_points", label: "对照必答方向", detail: "核对已覆盖和仍需补充的内容" },
  { key: "deciding_follow_up", label: "生成反馈与下一步", detail: "决定继续追问或进入下一题" },
] as const;

const evaluationStageOrder: Record<ReviewEvaluationStage, number> = {
  preparing: 1,
  checking_key_points: 2,
  deciding_follow_up: 3,
};

function ReviewEvaluationProcess({ startedAt, stage, stopping, onInterrupt }: { startedAt: string | null; stage: ReviewEvaluationStage; stopping: boolean; onInterrupt: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, [startedAt]);
  const effectiveStartedAt = startedAt ?? new Date(now).toISOString();
  const seconds = elapsedSeconds(effectiveStartedAt, new Date(now).toISOString()) ?? 0;
  const activeIndex = evaluationStageOrder[stage];
  const stageLabel = evaluationStages[activeIndex].label;
  const time = formatMessageTime(effectiveStartedAt);
  return <article className="review-chat-message review-chat-message--agent review-evaluation-process" role="status" aria-label="回答评价进度" aria-live="polite">
    <span className="review-chat-message__avatar" aria-hidden="true"><Bot size={17} /></span>
    <div className="review-chat-message__content">
      <div className="review-chat-message__meta"><strong>复习助手</strong>{time ? <span className="review-chat-message__timing"><time dateTime={effectiveStartedAt}>{time}</time><span>· 处理中 {formatElapsedSeconds(seconds)}</span></span> : null}</div>
      <div className="review-evaluation-process__card">
        <header><Activity size={16} aria-hidden="true" /><div><strong>{stageLabel}</strong><small>评价结果校验完成后会一次展示</small></div><Button type="button" size="sm" variant="ghost" disabled={stopping} onClick={onInterrupt}><Square size={13} />停止评价</Button></header>
        <ol>{evaluationStages.map((item, index) => {
          const state = index < activeIndex ? "completed" : index === activeIndex ? "active" : "pending";
          return <li key={item.key} data-state={state}><span aria-hidden="true">{state === "completed" ? <Check size={12} /> : null}</span><div><strong>{item.label}</strong><small>{item.detail}</small></div></li>;
        })}</ol>
      </div>
    </div>
  </article>;
}

function formatMessageTime(value: string) {
  return formatBeijingTime(value, false);
}

export function ReviewChatMessage({ message, pending = false, processingSeconds = null }: { message: ReviewTimelineMessage; pending?: boolean; processingSeconds?: number | null }) {
  const user = message.role === "user";
  const auxiliaryIntent = message.payload.auxiliary === true && typeof message.payload.intent === "string"
    ? message.payload.intent
    : null;
  const localResponseLabel = !user && auxiliaryIntent === "reveal_answer"
    ? "题库参考答案"
    : !user && auxiliaryIntent === "post_answer_reference"
      ? "题库参考答案"
    : !user && auxiliaryIntent === "request_hint"
      ? "题库提示"
      : null;
  const automaticReference = !user
    && auxiliaryIntent === "post_answer_reference"
    && message.payload.automaticReference === true;
  const evaluation = message.messageKind === "evaluation_card" ? message.payload.evaluation as { score?: string; evidence?: string; missing_key_points?: string[] } | undefined : undefined;
  const score = evaluation?.score === "good" ? "掌握良好" : evaluation?.score === "partial" ? "部分掌握" : evaluation?.score === "poor" ? "需要补充" : "评价完成";
  const time = formatMessageTime(message.createdAt);
  const showContent = !evaluation || message.content.trim() !== evaluation.evidence?.trim();
  return <article className={`review-chat-message review-chat-message--${user ? "user" : "agent"}${pending ? " is-pending" : ""}`}>
    <span className="review-chat-message__avatar" aria-hidden="true">{user ? <UserRound size={17} /> : <Bot size={17} />}</span>
    <div className="review-chat-message__content">
      <div className="review-chat-message__meta"><strong>{user ? "你" : localResponseLabel ?? "复习助手"}</strong>{localResponseLabel ? <span className="review-chat-message__local-badge">{automaticReference ? "答后对照 · 不影响本次掌握度" : "本地读取 · 0 Token"}</span> : null}{time ? <span className="review-chat-message__timing"><time dateTime={message.createdAt}>{time}</time>{!user && processingSeconds !== null ? <span>· {pending ? "已处理" : "耗时"} {formatElapsedSeconds(processingSeconds)}</span> : null}</span> : null}{pending && user ? <span>发送中…</span> : null}</div>
      <div className="review-chat-message__bubble">
        {showContent ? user ? <p>{message.content}</p> : <div className="review-chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div> : null}
        {evaluation ? <section className="review-evaluation-card"><strong>{score}</strong>{evaluation.evidence ? <p>{evaluation.evidence}</p> : null}{evaluation.missing_key_points?.length ? <details><summary>查看 {evaluation.missing_key_points.length} 个待补充关键点</summary><ol>{evaluation.missing_key_points.map((point) => <li key={point}>{point}</li>)}</ol></details> : null}</section> : null}
      </div>
    </div>
  </article>;
}

export function ReviewConversation({ round, optimisticMessage, busy, evaluationStage = "preparing", onSubmit, onSkip, onInterrupt, onRetry }: { round: ReviewRound; optimisticMessage: ReviewTimelineMessage | null; busy: boolean; evaluationStage?: ReviewEvaluationStage; onSubmit: (value: string, configuration: ReviewAnswerConfiguration) => Promise<unknown>; onSkip: () => void; onInterrupt: () => void; onRetry: () => void }) {
  const [answer, setAnswer] = useState("");
  const [selectedModel, setSelectedModel] = useState(round.settings.answer_model_id);
  const [reasoning, setReasoning] = useState<ReasoningEffort>(round.settings.reasoning_effort);
  const logRef = useRef<HTMLDivElement>(null);
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const models = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled ? provider.models.filter((model) => model.enabled).map((model) => ({ id: model.id, label: `${provider.name} / ${model.displayName}` })) : []), [providers.data]);
  const selectedModelLabel = models.find((model) => model.id === selectedModel)?.label ?? displayModel(selectedModel);
  const latestAttempt = round.attempts.at(-1);
  const evaluating = latestAttempt?.status === "evaluating";
  const failed = latestAttempt?.status === "evaluation_failed";
  const interrupted = failed && latestAttempt?.evaluationErrorCode === "evaluation_interrupted";
  const messages = round.messages.length > 0 ? round.messages : round.currentInput ? [{ id: round.currentInput.id, executionId: round.executionId, role: "assistant", content: round.currentInput.prompt, messageKind: "review_prompt", payload: {}, createdAt: round.currentInput.createdAt }] : [];
  const currentOrdinal = round.currentIndex + 1;
  const referenceShown = messages.some((message) =>
    message.role === "assistant"
    && message.payload.ordinal === currentOrdinal
    && (message.payload.intent === "post_answer_reference" || message.payload.intent === "reveal_answer"),
  );
  const processingSeconds = (message: ReviewTimelineMessage) => {
    if (message.role !== "assistant" || message.messageKind !== "evaluation_card") return null;
    const attemptId = typeof message.payload.attemptId === "string" ? message.payload.attemptId : typeof message.payload.resourceId === "string" ? message.payload.resourceId : null;
    const attempt = attemptId ? round.attempts.find((item) => item.id === attemptId) : null;
    return attempt?.evaluationStartedAt && attempt.evaluationCompletedAt ? elapsedSeconds(attempt.evaluationStartedAt, attempt.evaluationCompletedAt) : null;
  };
  useEffect(() => {
    const log = logRef.current;
    if (!log) return;
    const scrollToLatest = () => { log.scrollTop = log.scrollHeight; };
    scrollToLatest();
    const frame = globalThis.requestAnimationFrame?.(scrollToLatest);
    return () => { if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame); };
  }, [round.id, messages.length, optimisticMessage?.id, evaluating, failed]);
  useEffect(() => {
    setSelectedModel(round.settings.answer_model_id);
    setReasoning(round.settings.reasoning_effort);
  }, [round.id, round.settings.answer_model_id, round.settings.reasoning_effort]);
  async function submit() {
    const value = answer.trim();
    if (!value) return;
    await onSubmit(value, { providerModelId: selectedModel, reasoningEffort: reasoning });
    setAnswer("");
  }
  const keyboard = useAgentComposerKeyboard(() => {
    void submit().catch(() => undefined);
  });
  const submitAuxiliary = (value: string) => {
    void onSubmit(value, {
      providerModelId: selectedModel,
      reasoningEffort: reasoning,
    }).catch(() => undefined);
  };
  return <section className="review-conversation review-conversation--chat" aria-label="当前复习轮次">
    <h2 className="review-conversation__sr-title">{round.currentQuestion?.title ?? "当前复习轮次"}</h2>
    {round.currentQuestion ? <CurrentQuestionCard question={round.currentQuestion} busy={busy} referenceShown={referenceShown} onHint={() => submitAuxiliary("给点提示")} onReveal={() => submitAuxiliary("查看答案")} onSkip={onSkip} /> : null}
    <div ref={logRef} className="review-chat-log" role="log" aria-label="复习对话" aria-live="polite">{messages.map((message) => <ReviewChatMessage key={message.id} message={message} processingSeconds={processingSeconds(message)} />)}{optimisticMessage ? <ReviewChatMessage message={optimisticMessage} pending /> : null}{evaluating ? <ReviewEvaluationProcess startedAt={latestAttempt?.evaluationStartedAt ?? null} stage={evaluationStage} stopping={busy} onInterrupt={onInterrupt} /> : null}{failed ? <div className="review-evaluation-error"><AlertTriangle size={17} /><div><strong>{interrupted ? "评价已停止" : "评价暂时失败"}</strong><p>{interrupted ? "回答已经保存，可以继续评价或跳过本题。" : "你的回答已经保存，无需重新输入。"}</p></div><Button variant="secondary" size="sm" disabled={busy} onClick={onRetry}><RotateCcw size={15} />{interrupted ? "继续评价" : "重试评价"}</Button></div> : null}</div>
    {round.currentInput ? <footer className="curation-composer review-chat-composer review-round-composer"><label className="review-conversation__sr-title" htmlFor="review-answer">{round.currentInput.kind === "follow_up" ? "补充回答" : "你的回答"}</label><div className="review-chat-composer__field"><textarea id="review-answer" rows={1} value={answer} disabled={busy} onChange={(event) => setAnswer(event.target.value)} {...keyboard} placeholder={round.currentInput.kind === "follow_up" ? "补充你的思路…" : "输入你的回答…"} /><div className="curation-composer__toolbar"><details className="curation-composer__settings"><summary aria-disabled={busy} onClick={(event) => { if (busy) event.preventDefault(); }}><SlidersHorizontal size={16} aria-hidden="true" /><span>{selectedModelLabel} · {reasoningLabel[reasoning]}</span><ChevronDown size={15} aria-hidden="true" /></summary><div className="curation-composer__settings-panel" aria-label="模型与思考强度"><label htmlFor="review-answer-model">本次评价模型</label><SelectControl id="review-answer-model" controlSize="sm" aria-label="评价模型" value={selectedModel} disabled={busy} onChange={(event) => setSelectedModel(event.target.value)}>{selectedModel && !models.some((model) => model.id === selectedModel) ? <option value={selectedModel}>{displayModel(selectedModel)}</option> : null}{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</SelectControl><label htmlFor="review-answer-reasoning">思考强度</label><SelectControl id="review-answer-reasoning" controlSize="sm" aria-label="评价思考强度" value={reasoning} disabled={busy} onChange={(event) => setReasoning(event.target.value as ReasoningEffort)}>{Object.entries(reasoningLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</SelectControl></div></details><small>Shift+Enter 换行</small><div className="review-chat-composer__actions"><Button className="review-round-composer__skip" variant="ghost" disabled={busy} onClick={onSkip}><SkipForward size={16} />跳过</Button><Button className="curation-composer__send" aria-label="发送" title="发送" disabled={!answer.trim() || !selectedModel || busy} loading={busy} onClick={() => void submit().catch(() => undefined)}><Send size={18} /></Button></div></div></div></footer> : null}
  </section>;
}

const reasoningLabel = { none: "默认思考", low: "低强度", medium: "中等", high: "深入" } as const;

function displayModel(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value) ? "已绑定模型" : value;
}
