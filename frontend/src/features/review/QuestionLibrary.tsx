import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Search, ShieldCheck, SlidersHorizontal, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ActionCenter } from "../agent/ActionCenter";
import { listActions } from "../agent/hitlApi";
import type { PendingAction } from "../agent/hitlTypes";
import { requestPublication } from "../knowledge/draftApi";
import { Button } from "../../shared/ui/Button";
import type { KnowledgeSource } from "../knowledge/knowledgeTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { bulkDeleteQuestionCandidates, deleteQuestionCandidate, listAllQuestionCandidates, rewriteQuestionCandidate, updateActiveQuestionVersion, updateQuestionCandidate } from "./reviewApi";
import { QuestionDetailPanel } from "./QuestionDetailPanel";
import { groupLogicalQuestions } from "./questionGroups";
import type { QuestionCandidate } from "./reviewTypes";

const statusLabels: Record<QuestionCandidate["status"], string> = {
  draft: "草稿",
  review_pending: "待确认",
  published: "已入库",
  rejected: "待修改",
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

function matchesCandidateFilters(candidate: QuestionCandidate, filters: { query: string; topic: string; difficulty: string; sourceId: string; status: string }, omit?: "topic" | "status") {
  const needle = filters.query.trim().toLocaleLowerCase();
  if (needle && !candidate.question.title.toLocaleLowerCase().includes(needle) && !candidate.question.questionText.toLocaleLowerCase().includes(needle)) return false;
  if (omit !== "topic" && filters.topic && !candidate.question.topics.includes(filters.topic)) return false;
  if (filters.difficulty && candidate.question.difficulty !== filters.difficulty) return false;
  if (filters.sourceId && !candidate.sourceRefs.includes(filters.sourceId)) return false;
  if (omit !== "status" && filters.status && candidate.status !== filters.status) return false;
  return true;
}

interface QuestionLibraryProps {
  workspace: WorkspaceConfig;
  sources: KnowledgeSource[];
  initialCandidateId?: string | null;
  initialStatus?: QuestionCandidate["status"] | "";
  onOpenSession: (sessionId: string) => void;
  onOpenDirectSession: (session: import("./reviewTypes").CurationSession) => void;
  onBackToSessions: () => void;
}

export function QuestionLibrary({ workspace, sources, initialCandidateId = null, initialStatus = "", onOpenSession, onOpenDirectSession, onBackToSessions }: QuestionLibraryProps) {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [status, setStatus] = useState(initialStatus);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deletionNotice, setDeletionNotice] = useState("");
  const [versionNotice, setVersionNotice] = useState("");
  const [publicationRequest, setPublicationRequest] = useState<{ action: PendingAction; candidateId: string } | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const publicationActions = useQuery({ queryKey: ["pending-actions", workspace.id], queryFn: () => listActions(workspace.id, { status: "pending" }), refetchInterval: 5000 });
  const catalog = useQuery({ queryKey: ["review-candidates-overview", workspace.id], queryFn: () => listAllQuestionCandidates(workspace.id) });
  const sourceLabels = useMemo(() => Object.fromEntries(sources.map((source) => [source.id, source.originalFilename])), [sources]);
  const facetFilters = useMemo(() => ({ query, topic, difficulty, sourceId, status }), [query, topic, difficulty, sourceId, status]);
  const allGroups = useMemo(() => groupLogicalQuestions(catalog.data ?? []), [catalog.data]);
  const resultGroups = useMemo(() => allGroups.filter((group) => {
    if (status && group.status !== status) return false;
    return group.members.some((candidate) => matchesCandidateFilters(candidate, { ...facetFilters, status: "" }));
  }), [allGroups, facetFilters, status]);
  const selectedGroup = useMemo(() => resultGroups.find((group) => group.members.some((item) => item.id === selectedId)) ?? resultGroups[0] ?? null, [resultGroups, selectedId]);
  const selected = useMemo(() => selectedGroup?.members.find((item) => item.id === selectedId) ?? selectedGroup?.primary ?? null, [selectedGroup, selectedId]);
  const topicFacetGroups = useMemo(() => allGroups.filter((group) => (!status || group.status === status) && group.members.some((candidate) => matchesCandidateFilters(candidate, { ...facetFilters, topic: "", status: "" }))), [allGroups, facetFilters, status]);
  const topicCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of topicFacetGroups) {
      const groupTopics = new Set(group.topics.length > 0 ? group.topics : ["未分类"]);
      for (const groupTopic of groupTopics) counts.set(groupTopic, (counts.get(groupTopic) ?? 0) + 1);
    }
    if (topic && !counts.has(topic)) counts.set(topic, 0);
    return [...counts.entries()].sort(([left], [right]) => left.localeCompare(right, "zh-CN"));
  }, [topic, topicFacetGroups]);
  const statusCounts = useMemo(() => allGroups.filter((group) => group.members.some((candidate) => matchesCandidateFilters(candidate, { ...facetFilters, status: "" }, "status"))).reduce((counts, group) => ({ ...counts, [group.status]: counts[group.status] + 1 }), { draft: 0, review_pending: 0, published: 0, rejected: 0 }), [allGroups, facetFilters]);
  const pendingPublicationActions = publicationActions.data?.filter((action) => action.actionType === "knowledge.publish") ?? [];
  const publicationPendingCount = publicationRequest && !pendingPublicationActions.some((action) => action.id === publicationRequest.action.id) ? pendingPublicationActions.length + 1 : pendingPublicationActions.length;
  const hasFilters = Boolean(query || topic || difficulty || sourceId || status);
  const resultScope = topic ? `${topic}主题` : hasFilters ? "当前筛选结果" : "全部候选";
  useEffect(() => { if (!selectedId && resultGroups[0]) setSelectedId(resultGroups[0].primary.id); }, [resultGroups, selectedId]);
  useEffect(() => { if (initialCandidateId) setSelectedId(initialCandidateId); }, [initialCandidateId]);
  const invalidate = async () => Promise.all([
    client.invalidateQueries({ queryKey: ["review-candidates-overview", workspace.id] }),
    client.invalidateQueries({ queryKey: ["active-review-questions", workspace.id] }),
  ]);
  const save = useMutation({ mutationFn: (values: { version: number; title: string; questionText: string; referenceAnswer: string; keyPoints: string[] }) => updateQuestionCandidate(selected!.id, values), onSuccess: invalidate });
  const rewrite = useMutation({ mutationFn: (feedback: string) => rewriteQuestionCandidate(selected!.id, feedback), onSuccess: async (session) => { await invalidate(); onOpenDirectSession(session); } });
  const confirm = useMutation({ mutationFn: async () => { if (!selected?.draft) throw new Error("候选题没有草稿"); return requestPublication(selected.draft.id); }, onSuccess: (result) => {
    client.setQueryData<PendingAction[]>(["pending-actions", workspace.id], (current = []) => [result.action, ...current.filter((action) => action.id !== result.action.id)]);
    setPublicationRequest({ action: result.action, candidateId: selected!.id });
    setApprovalOpen(true);
  } });
  const promote = useMutation({ mutationFn: async () => {
    if (!selected || !publishedSibling) throw new Error("没有可替换的当前入库版");
    return updateActiveQuestionVersion(selected.id, publishedSibling.question.questionId, publishedSibling.question.contentHash, crypto.randomUUID());
  }, onSuccess: async () => { setVersionNotice("入库版已更新；旧版本已转为历史版本，已有复习轮次不受影响。"); await invalidate(); }, onError: () => setVersionNotice("更新入库版失败，当前版本可能已经变化，请刷新后重新比较。") });
  const remove = useMutation({ mutationFn: (targets: QuestionCandidate[]) => targets.length === 1 ? deleteQuestionCandidate(targets[0].id, targets[0].draft?.version ?? null) : bulkDeleteQuestionCandidates(workspace.id, targets), onSuccess: async (result) => {
    const removed = new Set(result.items.filter((item) => ["deleted", "already_deleted"].includes(item.status)).map((item) => item.candidateId));
    const unresolved = result.items.filter((item) => !removed.has(item.candidateId));
    setSelectedIds((current) => new Set([...current].filter((id) => !removed.has(id))));
    setSelectedId((current) => current && removed.has(current) ? null : current);
    setDeletionNotice(unresolved.length > 0 ? `已删除 ${removed.size} 道，${unresolved.length} 道因版本变化或不存在而未删除。` : `已将 ${removed.size} 道题移入题目回收站。`);
    await invalidate();
  }, onError: () => setDeletionNotice("删除未完成，请刷新题目状态后重试。") });
  const busy = save.isPending || rewrite.isPending || confirm.isPending || promote.isPending || remove.isPending;
  const publishedSibling = selectedGroup?.members.find((item) => item.status === "published" && item.id !== selected?.id) ?? null;
  const confirmDelete = (targets: QuestionCandidate[]) => { if (targets.length > 0 && globalThis.confirm(`将 ${targets.length} 道题移入题目回收站？已发布题会从可复习题库停用，但不会删除 Vault 文件。`)) remove.mutate(targets); };
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
          {publicationPendingCount > 0 && !approvalOpen ? <button type="button" className="question-library__approval-entry" aria-label={`打开待审批发布任务，共 ${publicationPendingCount} 项`} title="查看全部待审批题目" onClick={() => { setPublicationRequest(null); setApprovalOpen(true); }}><ShieldCheck size={16} /><span>待审批</span><strong>{publicationPendingCount}</strong></button> : null}
        </div>
      </header>

      <div className="question-library__workspace">
        <aside className="question-library__taxonomy" aria-label="题目分类">
          <header><strong>目录</strong></header>
          <button type="button" className="question-library__topic" aria-current={!topic} onClick={() => setTopic("")}><span>全部题目</span><strong>{topicFacetGroups.length}</strong></button>
          <div className="question-library__topic-group"><small>按主题</small>{topicCounts.map(([name, count]) => <button key={name} type="button" className="question-library__topic" aria-current={topic === name} onClick={() => setTopic(topic === name ? "" : name)}><span>{name}</span><strong>{count}</strong><ChevronRight size={14} /></button>)}</div>
        </aside>

        <section className="question-library__results" aria-label="题目结果">
          <header><strong>{resultGroups.length} 道逻辑题目</strong><span>{resultScope}</span>{selectedIds.size > 0 ? <div className="question-library__bulk"><span>已选 {selectedIds.size} 道</span><Button size="sm" variant="danger" loading={remove.isPending} onClick={() => confirmDelete((catalog.data ?? []).filter((item) => selectedIds.has(item.id)))}><Trash2 size={14} />批量删除</Button></div> : null}</header>
          {catalog.isLoading ? <p className="status-note">正在读取候选题…</p> : null}
          {deletionNotice ? <div className="question-library__notice" role="status"><span>{deletionNotice}</span><button type="button" aria-label="关闭删除结果" onClick={() => setDeletionNotice("")}><X size={14} /></button></div> : null}
          {!catalog.isLoading && resultGroups.length === 0 ? <div className="question-library__empty"><Search size={22} /><strong>{hasFilters ? "没有匹配的题目" : "题目库还是空的"}</strong><p>{hasFilters ? "尝试清除部分筛选条件。" : "返回整理会话，选择资料后使用 AI 整理。"}</p>{hasFilters ? <button type="button" onClick={resetFilters}>清除筛选</button> : <button type="button" onClick={onBackToSessions}>返回整理会话</button>}</div> : null}
          <div className="question-library__list" role="list">
            {resultGroups.map((group) => { const candidate = group.primary; return <div role="listitem" key={group.id} aria-current={group.id === selectedGroup?.id} className="question-library__row"><label className="question-library__select"><input type="checkbox" aria-label={`选择 ${candidate.question.title}`} checked={selectedIds.has(candidate.id)} onChange={(event) => setSelectedIds((current) => { const next = new Set(current); event.target.checked ? next.add(candidate.id) : next.delete(candidate.id); return next; })} /></label><button type="button" className="question-library__row-main" onClick={() => setSelectedId(candidate.id)}>
              <span className={`question-library__dot question-library__dot--${group.status}`} aria-hidden="true" />
              <span className="question-library__row-copy"><strong title={candidate.question.title}>{candidate.question.title}</strong><span>{group.topics.slice(0, 2).map((item) => <em key={item}>{item}</em>)}{group.members.length > 1 ? <em className="question-library__versions">{group.members.length - 1} 个相似版本</em> : null}</span></span>
              <span className="question-library__row-meta"><small>{difficultyLabels[candidate.question.difficulty]} · {updatedLabel(candidate.updatedAt)}</small><em className={`question-library__badge question-library__badge--${group.status}`}>{statusLabels[group.status]}</em></span>
            </button></div>; })}
          </div>
        </section>

        <div className="question-library__detail-stack">
          {selectedGroup && selectedGroup.members.length > 1 ? <section className="question-versions" aria-label="同题版本"><div><strong>同一逻辑题目的 {selectedGroup.members.length} 个版本</strong><span>同一时间只有一个当前入库版；历史版本和候选版本不会参与新复习。</span></div><div className="question-versions__list">{selectedGroup.members.map((member, index) => <button type="button" key={member.id} aria-pressed={member.id === selected?.id} onClick={() => { setSelectedId(member.id); setVersionNotice(""); }}><span>{member.isActiveVersion ? "当前入库版" : member.status === "published" ? "历史入库版" : `候选版本 ${index + 1}`}</span><small>{member.isActiveVersion ? "新复习使用" : member.status === "published" ? "仅供历史追溯" : `${statusLabels[member.status]} · ${updatedLabel(member.updatedAt)}`}</small></button>)}</div>{publishedSibling && selected?.status === "review_pending" ? <div className="question-versions__update"><div><strong>将这个候选设为新的入库版</strong><span>当前入库版会转为历史版本；已开始的复习轮次仍使用原快照。</span></div><Button loading={promote.isPending} disabled={busy && !promote.isPending} onClick={() => { if (globalThis.confirm(`用「${selected.question.title}」更新当前入库版？旧版会保留为历史版本。`)) promote.mutate(); }}>更新入库版</Button></div> : null}{versionNotice ? <p className="question-versions__notice" role="status">{versionNotice}</p> : null}</section> : null}
          <QuestionDetailPanel key={selected?.id ?? "empty"} candidate={selected} sourceLabels={sourceLabels} busy={busy} approvalPending={publicationRequest?.candidateId === selected?.id} publicationBlockedReason={publishedSibling ? `该候选属于「${publishedSibling.question.title}」。如内容更完整，请使用上方“更新入库版”；它不能作为第二道题重复发布。` : undefined} onSave={(values) => save.mutate(values)} onRewrite={(feedback) => rewrite.mutate(feedback)} onConfirm={() => confirm.mutate()} onDelete={() => selected && confirmDelete([selected])} onOpenSession={onOpenSession} />
        </div>
      </div>
    </section>
    {approvalOpen && (publicationRequest || publicationPendingCount > 0) ? <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setApprovalOpen(false); }}><section className="publication-approval-dialog" role="dialog" aria-modal="true" aria-label="题目发布审批" onKeyDown={(event) => { if (event.key === "Escape") setApprovalOpen(false); }}><header><div className="publication-approval-dialog__icon"><ShieldCheck size={20} /></div><div><h2>发布审批</h2><p>{publicationRequest ? "确认题目内容无误后，将它加入可复习题库。" : "先选择一道待审批题目，再查看内容并决定是否入库。"}</p></div><button type="button" aria-label="关闭发布审批" autoFocus onClick={() => setApprovalOpen(false)}><X size={18} /></button></header><ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" actionId={publicationRequest?.action.id} watchExecutionId={publicationRequest?.action.executionId} initialAction={publicationRequest?.action} requireSelection={!publicationRequest} presentation="publication" onResolved={() => { setPublicationRequest(null); setApprovalOpen(false); void invalidate(); }} /></section></div> : null}
  </>;
}
