import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Search, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ActionCenter } from "../agent/ActionCenter";
import { listActions } from "../agent/hitlApi";
import { requestPublication } from "../knowledge/draftApi";
import type { KnowledgeSource } from "../knowledge/knowledgeTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { Button } from "../../shared/ui/Button";
import { listQuestionBatches, listQuestionCandidates, rewriteQuestionCandidate, updateQuestionCandidate } from "./reviewApi";
import { QuestionDetailPanel } from "./QuestionDetailPanel";
import type { QuestionCandidate } from "./reviewTypes";

const statusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已入库",
  rejected: "已拒绝",
};

const difficultyLabels: Record<QuestionCandidate["question"]["difficulty"], string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

function updatedLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚更新";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" }).format(date);
}

function displayActionTitle(value: unknown) {
  return typeof value === "string" && value.trim() ? value : "待发布题目";
}

async function listAllQuestionCandidates(workspaceId: string, filters: { query?: string; topic?: string; difficulty?: string; sourceId?: string; status?: string } = {}) {
  const items: QuestionCandidate[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const batch = await listQuestionCandidates(workspaceId, { ...filters, page });
    items.push(...batch);
    if (batch.length < 50) break;
  }
  return items;
}

interface QuestionLibraryProps {
  workspace: WorkspaceConfig;
  sources: KnowledgeSource[];
  initialCandidateId?: string | null;
  onOpenSession: (sessionId: string) => void;
  onBackToSessions: () => void;
}

export function QuestionLibrary({ workspace, sources, initialCandidateId = null, onOpenSession, onBackToSessions }: QuestionLibraryProps) {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [status, setStatus] = useState("");
  const [publicationRequest, setPublicationRequest] = useState<{ executionId: string; candidateId: string; title: string } | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const publicationActions = useQuery({ queryKey: ["pending-actions", workspace.id], queryFn: () => listActions(workspace.id, { status: "pending" }), refetchInterval: 5000 });
  const batches = useQuery({ queryKey: ["review-batches", workspace.id], queryFn: () => listQuestionBatches(workspace.id), refetchInterval: (value) => value.state.data?.some((item) => item.status === "generating") ? 1200 : false });
  const catalog = useQuery({ queryKey: ["review-candidates-overview", workspace.id], queryFn: () => listAllQuestionCandidates(workspace.id) });
  const candidates = useQuery({ queryKey: ["review-candidates", workspace.id, query, topic, difficulty, sourceId, status], queryFn: () => listAllQuestionCandidates(workspace.id, { query, topic, difficulty, sourceId, status }) });
  const sourceLabels = useMemo(() => Object.fromEntries(sources.map((source) => [source.id, source.originalFilename])), [sources]);
  const selected = useMemo(() => candidates.data?.find((item) => item.id === selectedId) ?? candidates.data?.[0] ?? null, [candidates.data, selectedId]);
  const topicCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const candidate of catalog.data ?? []) {
      const primary = candidate.question.topics[0] || "未分类";
      counts.set(primary, (counts.get(primary) ?? 0) + 1);
    }
    return [...counts.entries()].sort(([left], [right]) => left.localeCompare(right, "zh-CN"));
  }, [catalog.data]);
  const statusCounts = useMemo(() => (catalog.data ?? []).reduce((counts, candidate) => ({ ...counts, [candidate.status]: counts[candidate.status] + 1 }), { draft: 0, review_pending: 0, published: 0, rejected: 0 }), [catalog.data]);
  const hasFilters = Boolean(query || topic || difficulty || sourceId || status);
  useEffect(() => { if (!selectedId && candidates.data?.[0]) setSelectedId(candidates.data[0].id); }, [candidates.data, selectedId]);
  useEffect(() => { if (initialCandidateId) setSelectedId(initialCandidateId); }, [initialCandidateId]);
  useEffect(() => {
    if (publicationRequest) return;
    const pending = publicationActions.data?.find((action) => action.actionType === "knowledge.publish");
    if (pending) setPublicationRequest({ executionId: pending.executionId, candidateId: "", title: displayActionTitle(pending.preview.title) });
  }, [publicationActions.data, publicationRequest]);
  const invalidate = async () => Promise.all([
    client.invalidateQueries({ queryKey: ["review-candidates", workspace.id] }),
    client.invalidateQueries({ queryKey: ["review-candidates-overview", workspace.id] }),
    client.invalidateQueries({ queryKey: ["review-batches", workspace.id] }),
  ]);
  const save = useMutation({ mutationFn: (values: { version: number; title: string; questionText: string; referenceAnswer: string; keyPoints: string[] }) => updateQuestionCandidate(selected!.id, values), onSuccess: invalidate });
  const rewrite = useMutation({ mutationFn: (feedback: string) => rewriteQuestionCandidate(selected!.id, feedback), onSuccess: async (session) => { await invalidate(); onOpenSession(session.id); } });
  const confirm = useMutation({ mutationFn: async () => { if (!selected?.draft) throw new Error("候选题没有草稿"); return requestPublication(selected.draft.id); }, onSuccess: (result) => { setPublicationRequest({ executionId: result.executionId, candidateId: selected!.id, title: selected!.question.title }); setApprovalOpen(true); } });
  const busy = save.isPending || rewrite.isPending || confirm.isPending;
  const resetFilters = () => { setQuery(""); setTopic(""); setDifficulty(""); setSourceId(""); setStatus(""); };

  return <>
    <section className="question-library" aria-label="题目库浏览器">
      <header className="question-library__toolbar">
        <label className="question-library__search"><Search size={17} /><input aria-label="搜索候选题" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、题目内容或标签" />{query ? <button type="button" aria-label="清空搜索" onClick={() => setQuery("")}><X size={15} /></button> : null}</label>
        <div className="question-library__filters" aria-label="题目筛选">
          <span className="question-library__filter-label">状态</span>
          {(["review_pending", "published", "rejected"] as const).map((value) => <button key={value} type="button" className={`question-library__status question-library__status--${value}`} aria-pressed={status === value} onClick={() => setStatus(status === value ? "" : value)}><span>{statusLabels[value]}</span><strong>{statusCounts[value]}</strong></button>)}
          <label><span>难度</span><select aria-label="难度筛选" value={difficulty} onChange={(event) => setDifficulty(event.target.value)}><option value="">全部</option><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select></label>
          <label><span>来源</span><select aria-label="来源筛选" value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">全部来源</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.originalFilename}</option>)}</select></label>
          <button type="button" className="question-library__clear" disabled={!hasFilters} onClick={resetFilters}><SlidersHorizontal size={15} />清除筛选</button>
        </div>
      </header>

      <div className="question-library__workspace">
        <aside className="question-library__taxonomy" aria-label="题目分类">
          <header><strong>目录</strong><button type="button" aria-label="返回整理会话" title="返回整理会话" onClick={onBackToSessions}><ArrowLeft size={16} /></button></header>
          <button type="button" className="question-library__topic" aria-current={!topic} onClick={() => setTopic("")}><span>全部题目</span><strong>{catalog.data?.length ?? 0}</strong></button>
          <div className="question-library__topic-group"><small>按主要主题</small>{topicCounts.map(([name, count]) => <button key={name} type="button" className="question-library__topic" aria-current={topic === name} onClick={() => setTopic(topic === name ? "" : name)}><span>{name}</span><strong>{count}</strong><ChevronRight size={14} /></button>)}</div>
        </aside>

        <section className="question-library__results" aria-label="题目结果">
          <header><strong>{candidates.data?.length ?? 0} 道题目</strong>{batches.data?.[0] ? <span>最近整理 {batches.data[0].candidateCount} 道</span> : null}</header>
          {candidates.isLoading ? <p className="status-note">正在读取候选题…</p> : null}
          {!candidates.isLoading && candidates.data?.length === 0 ? <div className="question-library__empty"><Search size={22} /><strong>{hasFilters ? "没有匹配的题目" : "题目库还是空的"}</strong><p>{hasFilters ? "尝试清除部分筛选条件。" : "返回整理会话，选择资料后使用 AI 整理。"}</p>{hasFilters ? <button type="button" onClick={resetFilters}>清除筛选</button> : <button type="button" onClick={onBackToSessions}>返回整理会话</button>}</div> : null}
          <div className="question-library__list" role="list">
            {(candidates.data ?? []).map((candidate) => <button type="button" role="listitem" key={candidate.id} aria-current={candidate.id === selected?.id} className="question-library__row" onClick={() => setSelectedId(candidate.id)}>
              <span className={`question-library__dot question-library__dot--${candidate.status}`} aria-hidden="true" />
              <span className="question-library__row-copy"><strong title={candidate.question.title}>{candidate.question.title}</strong><span>{candidate.question.topics.slice(0, 2).map((item) => <em key={item}>{item}</em>)}</span></span>
              <span className="question-library__row-meta"><small>{difficultyLabels[candidate.question.difficulty]} · {updatedLabel(candidate.updatedAt)}</small><em className={`question-library__badge question-library__badge--${candidate.status}`}>{statusLabels[candidate.status]}</em></span>
            </button>)}
          </div>
        </section>

        <QuestionDetailPanel key={selected?.id ?? "empty"} candidate={selected} sourceLabels={sourceLabels} busy={busy} approvalPending={publicationRequest?.candidateId === selected?.id} onSave={(values) => save.mutate(values)} onRewrite={(feedback) => rewrite.mutate(feedback)} onConfirm={() => confirm.mutate()} onOpenSession={onOpenSession} />
      </div>
    </section>
    {publicationRequest && approvalOpen ? <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setApprovalOpen(false); }}><section className="publication-approval-dialog" role="dialog" aria-modal="true" aria-label="题目发布审批" onKeyDown={(event) => { if (event.key === "Escape") setApprovalOpen(false); }}><header><div className="publication-approval-dialog__icon"><ShieldCheck size={20} /></div><div><h2>发布审批</h2><p>确认题目内容无误后，将它加入可复习题库。</p></div><button type="button" aria-label="关闭发布审批" autoFocus onClick={() => setApprovalOpen(false)}><X size={18} /></button></header><ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={publicationRequest.executionId} presentation="publication" onResolved={() => { setPublicationRequest(null); setApprovalOpen(false); void invalidate(); }} /></section></div> : null}
    {publicationRequest && !approvalOpen ? <aside className="publication-approval-reminder" role="status" aria-label="发布审批待处理"><div><ShieldCheck size={18} /><span><strong>发布审批待处理</strong><small>{publicationRequest.title}</small></span></div><Button size="sm" onClick={() => setApprovalOpen(true)}>继续审批</Button></aside> : null}
  </>;
}
