import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, Clock3, FileText, History, Pencil, RefreshCw, Save, Search, Sparkles, X } from "lucide-react";
import { MarkdownView } from "../knowledge/MarkdownView";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { BEIJING_TIME_ZONE, formatBeijingTimestamp, parseApiTimestamp } from "../../shared/time";
import type { JobTarget } from "../jobTargets/jobTargetTypes";
import {
  createRetrospectiveSearch,
  createRetrospectiveSearchReport,
  getRetrospectiveSearch,
  listRetrospectiveSearches,
  listRetrospectiveSearchReports,
  listRetrospectiveSearchResults,
  summarizeRetrospectiveSearch,
  updateRetrospectiveSearchReport,
} from "./retrospectiveApi";
import type { RetrospectiveSearchReport, RetrospectiveSearchResult, RetrospectiveSearchSet } from "./retrospectiveTypes";

export function RetrospectiveHistorySearch({
  workspaceId,
  targets,
  selectedSearchSetId,
  onSearchSetIdChange,
}: {
  workspaceId: string;
  targets: JobTarget[];
  selectedSearchSetId?: string | null;
  onSearchSetIdChange?: (searchSetId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [queryText, setQueryText] = useState("");
  const [jobTargetId, setJobTargetId] = useState("");
  const [localSearchSetId, setLocalSearchSetId] = useState<string | null>(null);
  const searchSetId = selectedSearchSetId === undefined ? localSearchSetId : selectedSearchSetId;
  const hydratedSearchSetId = useRef<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportTitle, setReportTitle] = useState("");
  const [reportFocus, setReportFocus] = useState<"question_summary" | "performance_review" | "preparation">("preparation");
  const [reportScope, setReportScope] = useState<"all" | "selected">("all");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState("");

  function changeSearchSetId(value: string | null) {
    if (selectedSearchSetId === undefined) setLocalSearchSetId(value);
    onSearchSetIdChange?.(value);
  }

  const searchesQuery = useQuery({
    queryKey: ["retrospective-history-searches", workspaceId],
    queryFn: ({ signal }) => listRetrospectiveSearches(workspaceId, signal),
    enabled: Boolean(workspaceId),
  });

  useEffect(() => {
    if (searchSetId || !searchesQuery.data?.[0]) return;
    const latest = searchesQuery.data[0];
    changeSearchSetId(latest.id);
    setQueryText(latest.queryText);
    setJobTargetId(typeof latest.filters.jobTargetId === "string" ? latest.filters.jobTargetId : "");
    hydratedSearchSetId.current = latest.id;
    // changeSearchSetId intentionally stays outside dependencies: the callback only mirrors selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchSetId, searchesQuery.data]);

  const searchMutation = useMutation({
    mutationFn: (input: { queryText: string; jobTargetId: string }) => createRetrospectiveSearch(workspaceId, input.queryText, {
      jobTargetId: input.jobTargetId || null,
    }),
    onSuccess: (value) => {
      changeSearchSetId(value.id);
      hydratedSearchSetId.current = value.id;
      setSelectedResultId(null);
      setSelectedReportId(null);
      void queryClient.invalidateQueries({ queryKey: ["retrospective-history-searches", workspaceId] });
    },
  });
  const searchQuery = useQuery({
    queryKey: ["retrospective-history-search", workspaceId, searchSetId],
    queryFn: ({ signal }) => getRetrospectiveSearch(workspaceId, searchSetId!, signal),
    enabled: Boolean(searchSetId),
    refetchInterval: (query) => {
      const value = query.state.data;
      return value?.status === "searching" || (value?.summaryExecutionId && !value.summaryMarkdown && !value.lastErrorCode) ? 1_000 : false;
    },
  });
  const resultsQuery = useQuery({
    queryKey: ["retrospective-history-results", workspaceId, searchSetId],
    queryFn: ({ signal }) => listRetrospectiveSearchResults(workspaceId, searchSetId!, signal),
    enabled: Boolean(searchSetId && searchQuery.data?.status === "completed"),
  });
  const reportsQuery = useQuery({
    queryKey: ["retrospective-history-reports", workspaceId],
    queryFn: ({ signal }) => listRetrospectiveSearchReports(workspaceId, signal),
    enabled: Boolean(workspaceId),
    refetchInterval: (query) => query.state.data?.some((item) => ["queued", "running"].includes(item.status)) ? 1_000 : false,
  });
  useEffect(() => {
    const value = searchQuery.data;
    if (!value || hydratedSearchSetId.current === value.id) return;
    setQueryText(value.queryText);
    setJobTargetId(typeof value.filters.jobTargetId === "string" ? value.filters.jobTargetId : "");
    hydratedSearchSetId.current = value.id;
  }, [searchQuery.data]);
  const selectedReport = reportsQuery.data?.find((item) => item.id === selectedReportId) ?? null;
  const reportResultsQuery = useQuery({
    queryKey: ["retrospective-history-results", workspaceId, selectedReport?.searchSetId],
    queryFn: ({ signal }) => listRetrospectiveSearchResults(workspaceId, selectedReport!.searchSetId!, signal),
    enabled: Boolean(selectedReport?.searchSetId),
  });
  const summaryMutation = useMutation({
    mutationFn: () => summarizeRetrospectiveSearch(workspaceId, searchSetId!),
    onSuccess: (value) => queryClient.setQueryData(["retrospective-history-search", workspaceId, value.id], value),
  });
  const reportMutation = useMutation({
    mutationFn: () => createRetrospectiveSearchReport(workspaceId, searchSetId!, {
      title: reportTitle.trim() || `${queryText || searchQuery.data?.queryText || "历史问题"}总结报告`,
      focus: reportFocus,
      selectedResultIds: reportScope === "selected" && selectedResultId ? [selectedResultId] : [],
    }),
    onSuccess: (value) => {
      setSelectedReportId(value.id);
      setReportOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["retrospective-history-reports", workspaceId] });
    },
  });
  const updateReportMutation = useMutation({
    mutationFn: (input: { reportId: string; expectedVersion: number; title: string; markdown: string }) => updateRetrospectiveSearchReport(workspaceId, input.reportId, input),
    onSuccess: (value) => {
      queryClient.setQueryData<RetrospectiveSearchReport[]>(["retrospective-history-reports", workspaceId], (items) => items?.map((item) => item.id === value.id ? value : item));
    },
  });

  const results = resultsQuery.data ?? [];
  useEffect(() => {
    if (!selectedResultId && results[0]) setSelectedResultId(results[0].id);
  }, [results, selectedResultId]);
  const selectedResult = results.find((item) => item.id === selectedResultId) ?? null;
  const grouped = useMemo(() => groupResults(results), [results]);
  const filteredSearches = useMemo(() => {
    const needle = historyFilter.trim().toLocaleLowerCase();
    if (!needle) return searchesQuery.data ?? [];
    return (searchesQuery.data ?? []).filter((item) => {
      const target = targetName(item, targets);
      return `${item.queryText} ${target} ${searchStatusLabel(item.status)}`.toLocaleLowerCase().includes(needle);
    });
  }, [historyFilter, searchesQuery.data, targets]);
  const searchGroups = useMemo(() => groupSearchHistory(filteredSearches), [filteredSearches]);

  function openReportSources(report: RetrospectiveSearchReport) {
    if (!report.searchSetId) return;
    changeSearchSetId(report.searchSetId);
    setSelectedReportId(null);
  }

  function openSearch(item: RetrospectiveSearchSet) {
    changeSearchSetId(item.id);
    hydratedSearchSetId.current = item.id;
    setQueryText(item.queryText);
    setJobTargetId(typeof item.filters.jobTargetId === "string" ? item.filters.jobTargetId : "");
    setSelectedResultId(null);
    setSelectedReportId(null);
    setHistoryOpen(false);
  }

  function rerunSearch(item: RetrospectiveSearchSet) {
    const target = typeof item.filters.jobTargetId === "string" ? item.filters.jobTargetId : "";
    setQueryText(item.queryText);
    setJobTargetId(target);
    setHistoryOpen(false);
    searchMutation.mutate({ queryText: item.queryText, jobTargetId: target });
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (queryText.trim()) searchMutation.mutate({ queryText: queryText.trim(), jobTargetId });
  }

  return <section className="history-search" aria-label="历史复盘检索">
    <header className="history-search__hero">
      <div><p>Workspace 历史检索</p><h2>跨多场面试，找到问题和证据</h2><span>先由 Agent 理解你的表达，再由确定性检索返回完整、可追溯的结果。</span></div>
      <form onSubmit={submit} className="history-search__form">
        <label><Search size={18} /><input aria-label="搜索历史复盘" value={queryText} onChange={(event) => setQueryText(event.target.value)} placeholder="例如：找出之前所有关于数字签名项目的问题" /></label>
        <SelectControl aria-label="历史检索求职目标" controlSize="sm" value={jobTargetId} onChange={(event) => setJobTargetId(event.target.value)}>
          <option value="">全部求职目标</option>
          {targets.map((target) => <option key={target.id} value={target.id}>{[target.companyName, target.roleName].filter(Boolean).join(" / ")}</option>)}
        </SelectControl>
        <Button type="submit" loading={searchMutation.isPending} disabled={!queryText.trim()}>开始检索</Button>
      </form>
      {searchMutation.isError ? <p className="history-search__error" role="alert">{searchMutation.error.message}</p> : null}
    </header>

    {!searchSetId ? <>
      {selectedReport ? <ReportArticle report={selectedReport} sources={reportResultsQuery.data ?? []} saving={updateReportMutation.isPending} onOpenSources={() => openReportSources(selectedReport)} onSave={(input) => updateReportMutation.mutateAsync({ reportId: selectedReport.id, expectedVersion: selectedReport.version, ...input })} /> : <div className="history-search__start"><span><Sparkles size={28} /></span><h3>问一个跨场次的问题</h3><p>搜索不会重新读取你的简历、画像或完整转写，只使用已经确认的面试问题和当时已保存的正式分析。</p><div><button type="button" onClick={() => setQueryText("帮我找出之前所有关于数字签名项目的问题")}>数字签名项目问过什么？</button><button type="button" onClick={() => setQueryText("哪些系统设计题反复出现，而且我的回答可以提升？")}>反复出现的系统设计题</button></div></div>}
      <ReportHistory reports={reportsQuery.data ?? []} selectedReportId={selectedReportId} onSelect={setSelectedReportId} />
    </> : null}

    {searchQuery.data ? <>
      <section className="history-search__current" aria-label="当前历史检索">
        <div>
          <span>当前检索</span>
          <strong>{searchQuery.data.queryText}</strong>
          <small><Clock3 size={14} />{formatSearchTime(searchQuery.data.updatedAt)}<i />{targetName(searchQuery.data, targets)}<i />{searchStatusLabel(searchQuery.data.status)}</small>
        </div>
        <Button variant="ghost" onClick={() => setHistoryOpen(true)}><History size={17} />检索记录 <em>{searchesQuery.data?.length ?? 0}</em></Button>
      </section>
      <div className="history-search__status">
        <div><strong>{searchQuery.data.status === "searching" ? "正在理解并检索" : `找到 ${searchQuery.data.totalQuestions} 道问题`}</strong><span>{searchQuery.data.status === "completed" ? `来自 ${searchQuery.data.totalRetrospectives} 场复盘 · 结果集已冻结` : "模型不可用时也会自动回退到确定性检索"}</span></div>
        <div><Button variant="ghost" disabled={!results.length || summaryMutation.isPending} loading={summaryMutation.isPending} onClick={() => summaryMutation.mutate()}><Sparkles size={16} />总结这些问题</Button><Button disabled={!results.length || reportMutation.isPending} loading={reportMutation.isPending} onClick={() => { setReportTitle(`${queryText || searchQuery.data?.queryText || "历史问题"}总结报告`); setReportOpen(true); }}><FileText size={16} />生成总结报告</Button></div>
      </div>
      {searchQuery.data.status === "failed" ? <div className="history-search__error" role="alert">检索没有完成：{searchQuery.data.lastErrorCode ?? "未知错误"}</div> : null}
      {searchQuery.data.summaryExecutionId && !searchQuery.data.summaryMarkdown && !searchQuery.data.lastErrorCode ? <article className="history-search__summary" role="status" aria-live="polite"><header><RefreshCw size={18} className="is-spinning" /><strong>Agent 正在总结当前冻结结果</strong><span>完成后会自动显示</span></header><p>你可以继续查看检索结果或离开页面，已启动的总结不会丢失。</p></article> : null}
      {searchQuery.data.summaryMarkdown ? <article className="history-search__summary"><header><Sparkles size={18} /><strong>Agent 总结</strong><span>{searchQuery.data.summaryCitationQuestionIds.length} 条题目引用</span></header><MarkdownView markdown={searchQuery.data.summaryMarkdown} /></article> : null}
      {searchQuery.data.summaryExecutionId && searchQuery.data.lastErrorCode && !searchQuery.data.summaryMarkdown ? <div className="history-search__error" role="alert">总结没有完成：{searchQuery.data.lastErrorCode}。检索结果仍然可以继续查看。</div> : null}
      {selectedReport ? <ReportArticle report={selectedReport} sources={reportResultsQuery.data ?? []} saving={updateReportMutation.isPending} onOpenSources={() => openReportSources(selectedReport)} onSave={(input) => updateReportMutation.mutateAsync({ reportId: selectedReport.id, expectedVersion: selectedReport.version, ...input })} /> : null}
      <div className="history-search__workspace">
        <div className="history-search__groups">
          {resultsQuery.isLoading ? <p>正在载入检索结果…</p> : grouped.map((group) => <section key={group.id}><header><Building2 size={16} /><div><strong>{group.title}</strong><span>{group.meta}</span></div><em>{group.items.length} 题</em></header>{group.items.map((item) => <button type="button" className={item.id === selectedResultId ? "is-selected" : ""} key={item.id} onClick={() => { setSelectedResultId(item.id); setSelectedReportId(null); }}><span>#{item.rank}</span><strong>{text(item.questionSnapshot.questionText)}</strong><small>{item.matchedTerms.join(" · ")}</small><ArrowRight size={15} /></button>)}</section>)}
          {!resultsQuery.isLoading && searchQuery.data.status === "completed" && !results.length ? <div className="history-search__none"><h3>没有找到符合条件的问题</h3><p>可以换一个项目别名、技术关键词，或放宽求职目标筛选。</p></div> : null}
        </div>
        <ResultDetail result={selectedResult} />
      </div>
      <ReportHistory reports={reportsQuery.data ?? []} selectedReportId={selectedReportId} onSelect={setSelectedReportId} />
      {reportOpen ? <div className="retrospective-confirm-backdrop" role="presentation"><section className="retrospective-confirm history-search__report-dialog" role="dialog" aria-modal="true" aria-labelledby="history-report-title"><FileText size={24} /><div><h3 id="history-report-title">生成历史复盘报告</h3><p>Agent 只读取当前冻结的检索结果；报告生成后可以继续编辑。</p><label>报告名称<input aria-label="历史报告名称" value={reportTitle} onChange={(event) => setReportTitle(event.target.value)} autoFocus /></label><label>报告侧重点<SelectControl aria-label="历史报告侧重点" value={reportFocus} onChange={(event) => setReportFocus(event.target.value as typeof reportFocus)}><option value="preparation">下一轮准备</option><option value="question_summary">问题归纳</option><option value="performance_review">表现复盘</option></SelectControl></label><label>报告范围<SelectControl aria-label="历史报告范围" value={reportScope} onChange={(event) => setReportScope(event.target.value as typeof reportScope)}><option value="all">当前全部 {results.length} 道问题</option><option value="selected" disabled={!selectedResultId}>当前选中的 1 道问题</option></SelectControl></label></div><footer><Button variant="ghost" onClick={() => setReportOpen(false)}>取消</Button><Button loading={reportMutation.isPending} disabled={!reportTitle.trim()} onClick={() => reportMutation.mutate()}>开始生成</Button></footer></section></div> : null}
    </> : null}
    {historyOpen ? <div className="history-search__history-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false); }}>
      <aside className="history-search__history" role="dialog" aria-modal="true" aria-labelledby="history-search-history-title">
        <header><div><span>Workspace 历史检索</span><h3 id="history-search-history-title">检索记录</h3><p>完整保留每次查询、筛选条件和冻结结果。</p></div><button type="button" aria-label="关闭检索记录" onClick={() => setHistoryOpen(false)}><X size={20} /></button></header>
        <label className="history-search__history-filter"><Search size={17} /><input autoFocus aria-label="筛选检索记录" value={historyFilter} onChange={(event) => setHistoryFilter(event.target.value)} placeholder="搜索问题、求职目标或状态" /></label>
        <div className="history-search__history-list">
          {searchGroups.map((group) => <section key={group.label}><h4>{group.label}<span>{group.items.length}</span></h4>{group.items.map((item) => {
            const reports = reportsQuery.data?.filter((report) => report.searchSetId === item.id) ?? [];
            return <article className={item.id === searchSetId ? "is-selected" : ""} key={item.id}>
              <button type="button" className="history-search__history-open" onClick={() => openSearch(item)}><strong>{item.queryText}</strong><span>{formatSearchTime(item.updatedAt)} · {targetName(item, targets)}</span><small className={`is-${item.status}`}>{searchStatusLabel(item.status)}</small><small>{item.totalQuestions} 题 · {item.totalRetrospectives} 场</small>{item.summaryMarkdown ? <em>有总结</em> : null}{reports.length ? <em>{reports.length} 份报告</em> : null}</button>
              <button type="button" className="history-search__history-rerun" aria-label={`再次检索：${item.queryText}`} disabled={searchMutation.isPending} onClick={() => rerunSearch(item)}><RefreshCw size={15} />再次检索</button>
            </article>;
          })}</section>)}
          {!searchGroups.length ? <div className="history-search__history-empty"><Search size={24} /><strong>没有匹配的检索记录</strong><span>换一个关键词，或清空筛选条件。</span></div> : null}
        </div>
      </aside>
    </div> : null}
  </section>;
}

function ReportHistory({ reports, selectedReportId, onSelect }: { reports: RetrospectiveSearchReport[]; selectedReportId: string | null; onSelect: (id: string) => void }) {
  if (!reports.length) return null;
  return <footer className="history-search__reports"><strong>历史报告</strong>{reports.map((report) => <button type="button" className={report.id === selectedReportId ? "is-selected" : ""} key={report.id} onClick={() => onSelect(report.id)}><FileText size={15} />{report.title}<span>{reportStatus(report)}</span></button>)}</footer>;
}

function ReportArticle({ report, sources, saving, onOpenSources, onSave }: { report: RetrospectiveSearchReport; sources: RetrospectiveSearchResult[]; saving: boolean; onOpenSources: () => void; onSave: (input: { title: string; markdown: string }) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(report.title);
  const [markdown, setMarkdown] = useState(report.markdown);
  useEffect(() => { setTitle(report.title); setMarkdown(report.markdown); setEditing(false); }, [report.id, report.version, report.title, report.markdown]);
  async function save() { await onSave({ title: title.trim(), markdown }); setEditing(false); }
  return <article className="history-search__report">
    <header><FileText size={18} />{editing ? <input aria-label="报告名称" value={title} onChange={(event) => setTitle(event.target.value)} /> : <strong>{report.title}</strong>}<span>第 {report.ordinal} 版 · 修订 {report.version} · {report.status === "completed" ? "已保存" : "生成中"}</span>{report.status === "completed" ? editing ? <><Button variant="ghost" onClick={() => { setTitle(report.title); setMarkdown(report.markdown); setEditing(false); }}><X size={15} />取消</Button><Button loading={saving} disabled={!title.trim() || !markdown.trim()} onClick={() => void save()}><Save size={15} />保存</Button></> : <Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={15} />编辑报告</Button> : null}</header>
    {editing ? <textarea aria-label="报告正文" value={markdown} onChange={(event) => setMarkdown(event.target.value)} /> : report.markdown ? <MarkdownView markdown={report.markdown} /> : report.status === "failed" ? <p>报告没有生成完成：{report.lastErrorCode ?? "未知错误"}</p> : <p>Agent 正在分批读取冻结结果并生成报告…</p>}
    {report.status === "completed" ? <details className="history-search__report-sources" open><summary>引用来源（{report.citationQuestionIds.length}）</summary>{report.citationQuestionIds.map((questionId) => { const source = sources.find((item) => item.questionUnitId === questionId); return <div key={questionId}><strong>{source ? text(source.questionSnapshot.questionText) : "来源问题暂不可用"}</strong><span>{source ? [text(source.sourceMetadata.companyName), text(source.sourceMetadata.roundLabel)].filter(Boolean).join(" · ") : questionId}</span></div>; })}<Button variant="ghost" disabled={!report.searchSetId} onClick={onOpenSources}>查看来源结果</Button></details> : null}
  </article>;
}

function ResultDetail({ result }: { result: RetrospectiveSearchResult | null }) {
  if (!result) return <aside className="history-search__detail history-search__detail--empty"><Search size={24} /><p>选择一道问题查看回答证据和正式分析。</p></aside>;
  const source = result.sourceMetadata;
  const analysis = result.analysisSnapshot;
  return <aside className="history-search__detail"><p>第 {result.rank} 条结果</p><h3>{text(result.questionSnapshot.questionText)}</h3><div className="history-search__source"><span>{text(source.companyName) || "公司未记录"}</span><span>{text(source.roleName)}</span><span>{text(source.roundLabel)}</span><span>{text(source.interviewDate)}</span></div><section><h4>当时的回答证据</h4><blockquote>{result.answerExcerpt || "原回答证据已不可用"}</blockquote></section><section><h4>正式复盘结论</h4><p className={`history-search__verdict is-${text(analysis.verdict)}`}>{verdictLabel(text(analysis.verdict))}</p>{list(analysis.improvements).map((item, index) => <p key={index}>{text((item as Record<string, unknown>).summary) || text(item)}</p>)}</section><footer>命中：{result.matchedTerms.join("、")}</footer></aside>;
}

function groupResults(results: RetrospectiveSearchResult[]) {
  const groups = new Map<string, { id: string; title: string; meta: string; items: RetrospectiveSearchResult[] }>();
  results.forEach((item) => {
    const id = item.retrospectiveId ?? `deleted-${item.id}`;
    const source = item.sourceMetadata;
    const group = groups.get(id) ?? { id, title: text(source.retrospectiveTitle) || "来源复盘已删除", meta: [text(source.companyName), text(source.roundLabel), text(source.interviewDate)].filter(Boolean).join(" · "), items: [] };
    group.items.push(item);
    groups.set(id, group);
  });
  return [...groups.values()];
}

function groupSearchHistory(items: RetrospectiveSearchSet[]) {
  const groups = new Map<string, RetrospectiveSearchSet[]>();
  items.forEach((item) => {
    const label = searchDateGroup(item.updatedAt);
    groups.set(label, [...(groups.get(label) ?? []), item]);
  });
  return [...groups.entries()].map(([label, groupItems]) => ({ label, items: groupItems }));
}

function searchDateGroup(value: string) {
  const date = parseApiTimestamp(value);
  if (Number.isNaN(date.getTime())) return "更早";
  const now = new Date();
  const difference = beijingDayNumber(now) - beijingDayNumber(date);
  if (difference <= 0) return "今天";
  if (difference === 1) return "昨天";
  if (difference <= 7) return "最近 7 天";
  const dateParts = beijingDateParts(date);
  const nowParts = beijingDateParts(now);
  if (dateParts.year === nowParts.year) return `${dateParts.month} 月`;
  return `${dateParts.year} 年`;
}

function formatSearchTime(value: string) {
  const date = parseApiTimestamp(value);
  if (Number.isNaN(date.getTime())) return value || "时间未记录";
  const sameDay = beijingDayNumber(date) === beijingDayNumber(new Date());
  return sameDay
    ? `今天 ${formatBeijingTimestamp(value, { hour: "2-digit", minute: "2-digit", hour12: false })}`
    : formatBeijingTimestamp(value, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) ?? value;
}

function beijingDayNumber(date: Date) {
  const parts = beijingDateParts(date);
  return Math.floor(Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000);
}

function beijingDateParts(date: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  return { year: value("year"), month: value("month"), day: value("day") };
}

function targetName(item: RetrospectiveSearchSet, targets: JobTarget[]) {
  const targetId = typeof item.filters.jobTargetId === "string" ? item.filters.jobTargetId : "";
  if (!targetId) return "全部求职目标";
  const target = targets.find((candidate) => candidate.id === targetId);
  return target ? [target.companyName, target.roleName].filter(Boolean).join(" / ") : "指定求职目标";
}

function searchStatusLabel(status: RetrospectiveSearchSet["status"]) {
  return ({ pending: "等待检索", searching: "检索中", completed: "已完成", failed: "检索失败" } as const)[status];
}

function text(value: unknown) { return typeof value === "string" ? value : value == null ? "" : String(value); }
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function verdictLabel(value: string) { return ({ strong: "回答扎实", improvable: "可以提升", high_risk: "优先改进", insufficient_evidence: "证据不足" } as Record<string, string>)[value] ?? value; }
function reportStatus(report: RetrospectiveSearchReport) { return report.status === "completed" ? `第 ${report.ordinal} 版` : report.status === "failed" ? "生成失败" : "生成中"; }
