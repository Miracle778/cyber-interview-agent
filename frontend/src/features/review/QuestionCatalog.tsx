import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Filter, Search, Sparkles, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { ActionCenter } from "../agent/ActionCenter";
import { requestPublication } from "../knowledge/draftApi";
import { listSources, uploadSource } from "../knowledge/knowledgeApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { createQuestionBatch, listQuestionBatches, listQuestionCandidates, rewriteQuestionCandidate, updateQuestionCandidate } from "./reviewApi";
import { QuestionDetailPanel } from "./QuestionDetailPanel";

export function QuestionCatalog({ workspace }: { workspace: WorkspaceConfig }) {
  const client = useQueryClient();
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [status, setStatus] = useState("");
  const [publicationExecutionId, setPublicationExecutionId] = useState<string | null>(null);
  const sources = useQuery({ queryKey: ["knowledge-sources", workspace.id], queryFn: () => listSources(workspace.id) });
  const batches = useQuery({ queryKey: ["review-batches", workspace.id], queryFn: () => listQuestionBatches(workspace.id), refetchInterval: (value) => value.state.data?.some((item) => item.status === "generating") ? 1200 : false });
  const candidates = useQuery({ queryKey: ["review-candidates", workspace.id, query, topic, difficulty, sourceId, status], queryFn: () => listQuestionCandidates(workspace.id, { query, topic, difficulty, sourceId, status }) });
  const sourceLabels = useMemo(() => Object.fromEntries((sources.data ?? []).map((source) => [source.id, source.originalFilename])), [sources.data]);
  const selected = useMemo(() => candidates.data?.find((item) => item.id === selectedId) ?? candidates.data?.[0] ?? null, [candidates.data, selectedId]);
  useEffect(() => { if (!selectedId && candidates.data?.[0]) setSelectedId(candidates.data[0].id); }, [candidates.data, selectedId]);
  const invalidate = async () => Promise.all([client.invalidateQueries({ queryKey: ["review-candidates", workspace.id] }), client.invalidateQueries({ queryKey: ["review-batches", workspace.id] })]);
  const organize = useMutation({ mutationFn: () => createQuestionBatch(workspace.id, selectedSources), onSuccess: invalidate });
  const save = useMutation({ mutationFn: (values: { version: number; title: string; questionText: string; referenceAnswer: string }) => updateQuestionCandidate(selected!.id, values), onSuccess: invalidate });
  const rewrite = useMutation({ mutationFn: (feedback: string) => rewriteQuestionCandidate(selected!.id, feedback), onSuccess: invalidate });
  const confirm = useMutation({ mutationFn: async () => { if (!selected?.draft) throw new Error("候选题没有草稿"); return requestPublication(selected.draft.id); }, onSuccess: (result) => setPublicationExecutionId(result.executionId) });
  const busy = organize.isPending || save.isPending || rewrite.isPending || confirm.isPending;

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    const result = await uploadSource(workspace.id, file);
    await client.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] });
    setSelectedSources((current) => [...new Set([...current, result.source.id])]);
  }

  return (
    <section className="catalog-workbench" aria-label="题库整理工作台">
      <header className="catalog-toolbar"><div><h2>题库整理</h2><p>导入资料后由 Agent 纠错、分类和去重；人工确认后才进入复习题库。</p></div><div className="btn-row"><label className="btn btn--secondary btn--md catalog-upload"><span className="btn__label"><Upload size={16} />导入文档</span><input type="file" aria-label="导入文档" onChange={(event) => void handleUpload(event.target.files?.[0])} /></label><Button disabled={selectedSources.length === 0 || busy} loading={organize.isPending} onClick={() => organize.mutate()}><Sparkles size={16} />AI 整理</Button></div></header>
      <div className="catalog-stats"><span>原始资料 {sources.data?.length ?? 0}</span><span>候选题 {candidates.data?.length ?? 0}</span><span>待确认 {candidates.data?.filter((item) => item.status === "review_pending").length ?? 0}</span><span>处理中 {batches.data?.filter((item) => item.status === "generating").length ?? 0}</span></div>
      <div className="source-picker" aria-label="选择整理资料">{sources.data?.map((source) => <label key={source.id}><input type="checkbox" checked={selectedSources.includes(source.id)} onChange={() => setSelectedSources((current) => current.includes(source.id) ? current.filter((id) => id !== source.id) : [...current, source.id])} />{source.originalFilename}</label>)}</div>
      <div className="catalog-grid">
        <aside className="catalog-list"><div className="catalog-filters"><label><Search size={15} /><input aria-label="搜索候选题" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目" /></label><label><Filter size={15} /><input aria-label="Topic 筛选" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Topic" /></label><label><select aria-label="难度筛选" value={difficulty} onChange={(event) => setDifficulty(event.target.value)}><option value="">全部难度</option><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select></label><label><select aria-label="来源筛选" value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">全部来源</option>{sources.data?.map((source) => <option key={source.id} value={source.id}>{source.originalFilename}</option>)}</select></label><label><select aria-label="状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="review_pending">待确认</option><option value="published">已入库</option><option value="rejected">已拒绝</option></select></label></div>{batches.data?.[0] ? <p className="batch-progress" role="status">最近批次：{batches.data[0].status} · {batches.data[0].candidateCount} 道候选</p> : null}{candidates.isLoading ? <p className="status-note">正在读取候选题…</p> : null}{!candidates.isLoading && candidates.data?.length === 0 ? <p className="status-note">暂无候选题。选择资料后点击“AI 整理”。</p> : null}{candidates.data?.map((candidate) => <button type="button" key={candidate.id} aria-current={candidate.id === selected?.id} className="candidate-row" onClick={() => setSelectedId(candidate.id)}><strong>{candidate.question.title}</strong><span>{candidate.question.topics.join(" / ")} · {candidate.question.difficulty}</span><small>{candidate.status === "review_pending" ? "待确认" : candidate.status}</small></button>)}</aside>
        <QuestionDetailPanel key={selected?.id ?? "empty"} candidate={selected} sourceLabels={sourceLabels} busy={busy} onSave={(values) => save.mutate(values)} onRewrite={(feedback) => rewrite.mutate(feedback)} onConfirm={() => confirm.mutate()} />
      </div>
      {publicationExecutionId ? <ActionCenter workspaceId={workspace.id} showDiagnostic={false} actionType="knowledge.publish" watchExecutionId={publicationExecutionId} onResolved={() => { setPublicationExecutionId(null); void invalidate(); }} /> : null}
    </section>
  );
}
