import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, MessagesSquare, RotateCcw, Trash2, X } from "lucide-react";
import { formatBeijingDate } from "../../shared/time";
import { Button } from "../../shared/ui/Button";
import { toActionableError } from "../../shared/api/errorAdvice";
import { deleteSource, listSources, restoreSource } from "../knowledge/knowledgeApi";
import { deleteCurationSession, emptyQuestionCandidateRecycleBin, listAllQuestionCandidates, listCurationSessions, permanentlyDeleteQuestionCandidate, restoreAllQuestionCandidates, restoreCurationSession, restoreQuestionCandidate } from "./reviewApi";

export function CurationRecycleBin({ open, workspaceId, onClose }: { open: boolean; workspaceId: string; onClose: () => void }) {
  const client = useQueryClient();
  const [operationNotice, setOperationNotice] = useState("");
  const sessions = useQuery({ queryKey: ["review-curation-trash", workspaceId], queryFn: () => listCurationSessions(workspaceId, true), enabled: open });
  const sources = useQuery({ queryKey: ["knowledge-source-trash", workspaceId], queryFn: () => listSources(workspaceId, true), enabled: open });
  const questions = useQuery({ queryKey: ["review-question-trash", workspaceId], queryFn: () => listAllQuestionCandidates(workspaceId, { deletedOnly: true }), enabled: open });
  const refresh = async () => Promise.all([
    client.invalidateQueries({ queryKey: ["review-curation-trash", workspaceId] }),
    client.invalidateQueries({ queryKey: ["knowledge-source-trash", workspaceId] }),
    client.invalidateQueries({ queryKey: ["review-curation-sessions", workspaceId] }),
    client.invalidateQueries({ queryKey: ["knowledge-sources", workspaceId] }),
    client.invalidateQueries({ queryKey: ["review-question-trash", workspaceId] }),
    client.invalidateQueries({ queryKey: ["review-question-candidates", workspaceId] }),
  ]);
  const restore = useMutation({
    mutationFn: async ({ kind, id }: { kind: "session" | "source" | "question"; id: string }) => kind === "session" ? restoreCurationSession(id) : kind === "question" ? restoreQuestionCandidate(id) : restoreSource(workspaceId, id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async ({ kind, id }: { kind: "session" | "source" | "question"; id: string }) => kind === "session" ? deleteCurationSession(id, true) : kind === "question" ? permanentlyDeleteQuestionCandidate(id) : deleteSource(workspaceId, id, true),
    onSuccess: async (_result, variables) => {
      if (variables.kind === "question") setOperationNotice("题目已永久删除");
      await refresh();
    },
  });
  const questionBulk = useMutation({
    mutationFn: async (action: "restore" | "empty") => action === "restore" ? restoreAllQuestionCandidates(workspaceId) : emptyQuestionCandidateRecycleBin(workspaceId),
    onSuccess: async (result, action) => {
      setOperationNotice(action === "restore" ? `已恢复 ${result.affectedCount} 道题` : `已永久删除 ${result.affectedCount} 道题`);
      await refresh();
    },
  });
  if (!open) return null;
  function permanentlyDelete(kind: "session" | "source" | "question", id: string, title = "") {
    const message = kind === "session"
      ? "永久删除会话后，聊天、执行记录和 checkpoint 无法恢复；关联题目、来源证据和发布记录会保留。确定继续？"
      : kind === "question"
        ? `永久删除“${title}”后无法恢复；已发布文件和发布审计记录仍会保留。确定继续？`
        : "永久删除原材料后无法恢复；存在题目证据引用时系统会阻止。确定继续？";
    if (globalThis.confirm(message)) remove.mutate({ kind, id });
  }
  function restoreAllQuestions() {
    setOperationNotice("");
    questionBulk.mutate("restore");
  }
  function emptyQuestions() {
    const count = questions.data?.length ?? 0;
    if (globalThis.confirm(`将永久删除回收站中的 ${count} 道题，删除后无法恢复。已发布文件和发布审计记录仍会保留。确定继续？`)) {
      setOperationNotice("");
      questionBulk.mutate("empty");
    }
  }
  const empty = !sessions.isPending && !sources.isPending && !questions.isPending && sessions.data?.length === 0 && sources.data?.length === 0 && questions.data?.length === 0;
  const mutationError = restore.error ?? remove.error ?? questionBulk.error;
  const error = mutationError ? toActionableError(mutationError, "回收站操作失败") : null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="curation-recycle-bin" role="dialog" aria-modal="true" aria-labelledby="recycle-bin-title">
      <header><div><span>资源管理</span><h2 id="recycle-bin-title">回收站</h2><p>归档会话、已删除题目和原材料分别管理，互不级联。</p></div><button type="button" aria-label="关闭回收站" onClick={onClose}><X size={20} /></button></header>
      <div className="curation-recycle-bin__body">
        {error ? <div className="inline-alert inline-alert--error" role="alert"><strong>{error.message}</strong><span>{error.advice}</span></div> : null}
        {operationNotice ? <div className="inline-alert inline-alert--success" role="status"><strong>{operationNotice}</strong></div> : null}
        {empty ? <div className="curation-recycle-bin__empty"><Trash2 size={28} /><strong>回收站是空的</strong><p>软删除的内容会显示在这里，永久删除不会进入回收站。</p></div> : null}
        {(sessions.data?.length ?? 0) > 0 ? <section aria-labelledby="deleted-session-title"><div className="review-pane-title"><MessagesSquare size={17} /><strong id="deleted-session-title">已归档会话</strong><span>{sessions.data?.length}</span></div>{sessions.data?.map((session) => <article key={session.id}><div><strong>{session.title}</strong><small>{session.sources.length} 份资料 · 永久删除会话不会删除题目</small></div><div><Button size="sm" variant="secondary" loading={restore.isPending} onClick={() => restore.mutate({ kind: "session", id: session.id })}><RotateCcw size={15} />恢复</Button><Button size="sm" variant="danger" loading={remove.isPending} onClick={() => permanentlyDelete("session", session.id)}>永久删除</Button></div></article>)}</section> : null}
        {(questions.data?.length ?? 0) > 0 ? <section aria-labelledby="deleted-question-title">
          <div className="review-pane-title recycle-section-title">
            <Trash2 size={17} />
            <strong id="deleted-question-title">已删除题目</strong>
            <span>{questions.data?.length}</span>
            <div className="recycle-section-title__actions">
              <Button size="sm" variant="secondary" loading={questionBulk.isPending && questionBulk.variables === "restore"} disabled={questionBulk.isPending || remove.isPending} onClick={restoreAllQuestions}><RotateCcw size={15} />全部恢复</Button>
              <Button size="sm" variant="danger" loading={questionBulk.isPending && questionBulk.variables === "empty"} disabled={questionBulk.isPending || remove.isPending} onClick={emptyQuestions}><Trash2 size={15} />清空题目</Button>
            </div>
          </div>
          {questions.data?.map((candidate) => <article key={candidate.id}><div><strong>{candidate.question.title}</strong><small>{candidate.status === "published" ? "已入库 · 恢复后重新启用" : "未入库"}{candidate.deletionReason ? ` · ${candidate.deletionReason}` : ""}</small></div><div><Button size="sm" variant="secondary" loading={restore.isPending && restore.variables?.id === candidate.id} disabled={questionBulk.isPending || remove.isPending} onClick={() => restore.mutate({ kind: "question", id: candidate.id })}><RotateCcw size={15} />恢复题目</Button><Button aria-label={`永久删除 ${candidate.question.title}`} size="sm" variant="danger" loading={remove.isPending && remove.variables?.id === candidate.id} disabled={questionBulk.isPending || restore.isPending} onClick={() => permanentlyDelete("question", candidate.id, candidate.question.title)}>永久删除</Button></div></article>)}
        </section> : null}
        {(sources.data?.length ?? 0) > 0 ? <section aria-labelledby="deleted-source-title"><div className="review-pane-title"><FileText size={17} /><strong id="deleted-source-title">原材料</strong><span>{sources.data?.length}</span></div>{sources.data?.map((source) => <article key={source.id}><div><strong>{source.originalFilename}</strong><small>{formatBeijingDate(source.createdAt) ?? source.createdAt}</small></div><div><Button size="sm" variant="secondary" loading={restore.isPending} onClick={() => restore.mutate({ kind: "source", id: source.id })}><RotateCcw size={15} />恢复</Button><Button size="sm" variant="danger" loading={remove.isPending} onClick={() => permanentlyDelete("source", source.id)}>永久删除</Button></div></article>)}</section> : null}
      </div>
    </section>
  </div>;
}
