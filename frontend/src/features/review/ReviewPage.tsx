import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, ClipboardCheck, Inbox, MessageSquareText } from "lucide-react";
import { Link } from "react-router-dom";
import type { AgentSession, AgentSessionDetail } from "../agent/agentTypes";
import type { PendingAction } from "../agent/hitlTypes";
import { useAgentEvents } from "../agent/useAgentEvents";
import type { KnowledgeDraft } from "../knowledge/draftTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import {
  approveAction,
  createAgentSession,
  getAgentSession,
  getDraft,
  listActions,
  listAgentSessions,
  rejectAction,
  startAgentExecution,
} from "./reviewSessionApi";
import type { ReviewQuestion } from "./reviewTypes";

interface ReviewPageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
}

type Evaluation = {
  score: "poor" | "partial" | "good";
  missing_key_points: string[];
  evidence: string;
};

export function ReviewPage({ workspace, draftQuestion }: ReviewPageProps) {
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentSessionDetail | null>(null);
  const [action, setAction] = useState<PendingAction | null>(null);
  const [draft, setDraft] = useState<KnowledgeDraft | null>(null);
  const [answer, setAnswer] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<ActionableError | null>(null);
  const [busy, setBusy] = useState(false);
  const stream = useAgentEvents(sessionId);

  const refreshSession = useCallback(async (targetId: string) => {
    const nextDetail = await getAgentSession(targetId);
    setDetail(nextDetail);
    if (!workspace) return;
    const actions = await listActions(workspace.id, { sessionId: targetId });
    const latest = actions.at(-1) ?? null;
    setAction(latest);
    const draftId = latest?.preview.draftId;
    setDraft(typeof draftId === "string" ? await getDraft(draftId) : null);
  }, [workspace]);

  useEffect(() => {
    if (!workspace) {
      setSessions([]);
      setSessionId(null);
      setDetail(null);
      return;
    }
    let cancelled = false;
    void listAgentSessions(workspace.id).then((items) => {
      if (cancelled) return;
      const reviewSessions = items.filter((item) => item.kind === "review.single");
      setSessions(reviewSessions);
      const latest = reviewSessions[0] ?? null;
      setSessionId(latest?.id ?? null);
      if (latest) void refreshSession(latest.id);
    }).catch((caught) => {
      if (!cancelled) setError(toActionableError(caught, "恢复复习会话失败"));
    });
    return () => { cancelled = true; };
  }, [workspace, refreshSession]);

  useEffect(() => {
    if (sessionId && stream.events.length > 0) void refreshSession(sessionId);
  }, [sessionId, stream.events.length, refreshSession]);

  const evaluation = useMemo(() => {
    const value = action?.preview.evaluation;
    return value && typeof value === "object" ? value as Evaluation : null;
  }, [action]);
  const shownQuestion = (action?.preview.question as ReviewQuestion | undefined) ?? draftQuestion;

  async function handleRunReview() {
    setError(null);
    if (!workspace || !draftQuestion) {
      setError(toActionableError(new Error("请先上传资料生成题库草稿"), "复习评估失败"));
      return;
    }
    if (!answer.trim()) {
      setError(toActionableError(new Error("请输入你的回答"), "复习评估失败"));
      return;
    }
    setBusy(true);
    try {
      let targetId = sessionId;
      if (!targetId || detail?.latestExecution?.status === "completed" || detail?.latestExecution?.status === "failed") {
        const created = await createAgentSession({
          workspaceId: workspace.id,
          kind: "review.single",
          title: `单题复习：${draftQuestion.title}`,
        });
        targetId = created.id;
        setSessions((current) => [...current, created]);
        setSessionId(targetId);
      }
      await startAgentExecution(targetId, {
        question: draftQuestion,
        user_answer: answer.trim(),
      });
      await refreshSession(targetId);
    } catch (caught) {
      setError(toActionableError(caught, "复习评估失败"));
    } finally {
      setBusy(false);
    }
  }

  async function resolve(decision: "approve" | "reject") {
    if (!action) return;
    if (decision === "reject" && !rejectReason.trim()) {
      setError(toActionableError(new Error("请填写拒绝原因"), "处理发布请求失败"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const request = {
        version: action.version,
        idempotencyKey: `${decision}-${action.id}-${action.version}`,
      };
      if (decision === "approve") await approveAction(action.id, request);
      else await rejectAction(action.id, { ...request, reason: rejectReason.trim() });
      if (sessionId) await refreshSession(sessionId);
    } catch (caught) {
      setError(toActionableError(caught, "处理发布请求失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page-section" aria-labelledby="review-title">
      <div className="page-section__header">
        <span className="page-section__icon" aria-hidden="true"><MessageSquareText size={18} /></span>
        <h2 id="review-title" className="page-section__title">复习</h2>
        {shownQuestion ? <Badge tone="primary">单题 · 持久化会话</Badge> : null}
      </div>

      <section className="review-session-bar" aria-label="复习会话">
        {sessions.length > 0 ? (
          <label className="field">
            <span className="field__label">历史会话</span>
            <select className="field__input" value={sessionId ?? ""} onChange={(event) => {
              setSessionId(event.target.value);
              void refreshSession(event.target.value);
            }}>
              {sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
            </select>
          </label>
        ) : <p className="status-note">完成一次回答后，会话会保存在这里</p>}
        {detail?.usage ? <div className="review-runtime-meta" aria-label="运行用量">
          <span>{detail.usage.totalTokens} tokens</span>
          {detail.usage.estimatedCount > 0 ? <span>含 {detail.usage.estimatedCount} 次估算</span> : null}
          {detail.contextCompacted ? <span>上下文已压缩</span> : null}
        </div> : null}
        {detail?.latestWarning ? <div className="status-note" role="alert">
          <span>{detail.latestWarning.message}</span>
          <span>{toActionableError(new Error(detail.latestWarning.code), "运行保护已触发").advice}</span>
        </div> : null}
      </section>

      <section className="review-practice" aria-label="当前练习">
        <Card title="复习对话" icon={<MessageSquareText size={18} />}>
          {!shownQuestion ? <div className="empty-state"><Inbox size={20} /><p>请先上传资料生成题库草稿</p><Link className="text-link" to="/knowledge">前往知识库</Link></div> : null}
          {shownQuestion ? <article aria-label="当前题目"><h3>{shownQuestion.title}</h3><p>{shownQuestion.questionText}</p></article> : null}
          {detail?.messages.map((message) => <p key={message.id} className="result-line"><strong>{message.role === "user" ? "你" : "Agent"}：</strong>{message.content}</p>)}
          <div className="field"><label className="field__label" htmlFor="reviewAnswer">你的回答</label><textarea id="reviewAnswer" className="field__input field__input--area" value={answer} disabled={!draftQuestion || busy} onChange={(event) => setAnswer(event.target.value)} /></div>
          <Button onClick={handleRunReview} disabled={!draftQuestion || busy} loading={busy}>发送回答</Button>
          {sessionId ? <p className="muted-text">事件流：{stream.status}</p> : null}
        </Card>
      </section>

      {evaluation || draft ? <section className="review-results" aria-label="复习结果">
        <Card title="复习报告" icon={<ClipboardCheck size={18} />}>
          {evaluation ? <><p>评分：{evaluation.score}</p><p>缺失点：{evaluation.missing_key_points.join("、") || "无"}</p><p>证据：{evaluation.evidence}</p></> : null}
          {draft ? <><pre className="report-preview">{draft.markdown}</pre><p>草稿状态：{draft.status}</p>{draft.publication ? <><p>发布状态：{draft.publication.state}</p><p>目标路径：{draft.publication.targetPath}</p>{draft.publication.state === "index_stale" ? <p role="alert">索引需要重新扫描</p> : null}</> : null}</> : null}
        </Card>
      </section> : null}

      {action?.status === "pending" ? <Card title="发布审批" icon={<ClipboardCheck size={18} />}>
        <p>报告已保存为草稿，批准后才会写入 Vault。</p>
        <div className="field"><label className="field__label" htmlFor="rejectReason">拒绝原因</label><input id="rejectReason" className="field__input" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} /></div>
        <div className="btn-row"><Button onClick={() => void resolve("approve")} disabled={busy}>批准发布</Button><Button onClick={() => void resolve("reject")} disabled={busy}>拒绝</Button></div>
      </Card> : null}

      {(error || stream.executionError) ? <div className="error-banner" role="alert"><AlertCircle size={16} /><span>错误：{error?.message ?? stream.executionError?.message}</span><span>{error?.advice ?? "下一步：检查模型绑定和 Provider 连接后重试"}</span></div> : null}
    </section>
  );
}
