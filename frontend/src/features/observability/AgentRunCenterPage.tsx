import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { WorkspaceConfig } from "../settings/settingsApi";
import {
  ExecutionList,
  executionNeedsAction,
  executionResultSummary,
  executionTaskTitle,
} from "./ExecutionList";
import { ExecutionPreview } from "./ExecutionPreview";
import {
  listObservabilityExecutions,
  ObservabilityPayloadError,
} from "./observabilityApi";
import type {
  ExecutionFilters,
  ExecutionSummary,
} from "./observabilityTypes";
import { useObservabilityEvents } from "./useObservabilityEvents";
import "./observability.css";
import "./runCenterFriendly.css";


interface AgentRunCenterPageProps {
  workspace: WorkspaceConfig | null;
}

const PAGE_SIZE = 10;

const EMPTY_FILTERS: ExecutionFilters = {
  search: "",
  status: "",
  agentName: "",
  includeSystemAgents: false,
};

const STATUS_GROUPS: Record<string, Set<string>> = {
  needs_me: new Set([
    "queued",
    "waiting_for_input",
    "waiting_for_approval",
    "partial_success",
    "failed",
  ]),
  waiting: new Set([
    "queued",
    "waiting_for_input",
    "waiting_for_approval",
  ]),
  attention: new Set(["partial_success", "failed"]),
  stopped: new Set(["interrupted", "cancelled"]),
};

function matchesFilters(
  execution: ExecutionSummary,
  filters: ExecutionFilters,
) {
  if (!filters.includeSystemAgents && execution.system) return false;
  if (
    filters.status &&
    (STATUS_GROUPS[filters.status]
      ? !STATUS_GROUPS[filters.status].has(execution.status)
      : execution.status !== filters.status)
  ) return false;
  if (
    filters.agentName &&
    execution.displayName !== filters.agentName &&
    execution.graphId !== filters.agentName
  ) return false;
  const search = filters.search.trim().toLocaleLowerCase();
  if (
    search &&
    !`${execution.title} ${execution.displayName} ${execution.graphId}`
      .toLocaleLowerCase()
      .includes(search)
  ) return false;
  return true;
}

function countStatuses(
  executions: ExecutionSummary[],
  statuses: Set<string> | string,
) {
  return executions.filter((execution) =>
    typeof statuses === "string"
      ? execution.status === statuses
      : statuses.has(execution.status)
  ).length;
}

function actionLabel(execution: ExecutionSummary) {
  if (["waiting_for_input", "waiting_for_approval"].includes(execution.status)) {
    return "继续处理";
  }
  if (execution.status === "queued") return "查看进度";
  return "查看并处理";
}

function defaultPreviewOpen() {
  return globalThis.matchMedia?.("(min-width: 1024px)").matches ?? true;
}

export function AgentRunCenterPage({
  workspace,
}: AgentRunCenterPageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState<ExecutionFilters>(() => ({
    search: searchParams.get("search") ?? "",
    status: searchParams.get("status") ?? "",
    agentName: searchParams.get("agentName") ?? "",
    includeSystemAgents: searchParams.get("includeSystemAgents") === "true",
  }));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(defaultPreviewOpen);
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [liveById, setLiveById] = useState<Record<string, ExecutionSummary>>({});
  const previousWorkspaceId = useRef(workspace?.id);
  const defaultStatusApplied = useRef(false);
  const onExecutionChanged = useCallback((execution: ExecutionSummary) => {
    setLiveById((current) => ({ ...current, [execution.id]: execution }));
  }, []);
  const connectionStatus = useObservabilityEvents(
    workspace?.id ?? null,
    onExecutionChanged,
  );
  const query = useQuery({
    queryKey: [
      "agent-observability",
      "executions",
      workspace?.id,
      filters.includeSystemAgents,
    ],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) =>
      listObservabilityExecutions(
        workspace!.id,
        {
          ...EMPTY_FILTERS,
          includeSystemAgents: filters.includeSystemAgents,
        },
        signal,
      ),
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    if (previousWorkspaceId.current === workspace?.id) return;
    previousWorkspaceId.current = workspace?.id;
    defaultStatusApplied.current = false;
    setSelectedId(null);
    setPreviewOpen(defaultPreviewOpen());
    setLiveById({});
    setFilters(EMPTY_FILTERS);
    setPage(1);
  }, [workspace?.id]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (filters.search.trim()) next.set("search", filters.search.trim());
    if (filters.status) next.set("status", filters.status);
    if (filters.agentName) next.set("agentName", filters.agentName);
    if (filters.includeSystemAgents) next.set("includeSystemAgents", "true");
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [filters, searchParams, setSearchParams]);

  const allExecutions = useMemo(() => {
    const byId = new Map<string, ExecutionSummary>();
    for (const execution of query.data?.items ?? []) {
      byId.set(execution.id, liveById[execution.id] ?? execution);
    }
    for (const execution of Object.values(liveById)) {
      if (!byId.has(execution.id)) byId.set(execution.id, execution);
    }
    return [...byId.values()].filter((execution) =>
      filters.includeSystemAgents || !execution.system
    );
  }, [filters.includeSystemAgents, liveById, query.data?.items]);

  const executions = useMemo(
    () => allExecutions.filter((execution) => matchesFilters(execution, filters)),
    [allExecutions, filters],
  );
  const actionItems = useMemo(
    () => allExecutions.filter(executionNeedsAction),
    [allExecutions],
  );
  const totalPages = Math.max(1, Math.ceil(executions.length / PAGE_SIZE));
  const visibleExecutions = executions.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE,
  );

  useEffect(() => {
    if (
      defaultStatusApplied.current ||
      query.isPending ||
      query.isError
    ) return;
    defaultStatusApplied.current = true;
    if (!searchParams.has("status") && actionItems.length > 0) {
      setFilters((current) => (
        current.status ? current : { ...current, status: "needs_me" }
      ));
    }
  }, [actionItems.length, query.isError, query.isPending, searchParams]);

  useEffect(() => {
    setPage(1);
  }, [
    filters.agentName,
    filters.includeSystemAgents,
    filters.search,
    filters.status,
  ]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  useEffect(() => {
    if (selectedId && executions.some((item) => item.id === selectedId)) return;
    setSelectedId(executions[0]?.id ?? null);
  }, [executions, selectedId]);

  const selected =
    allExecutions.find((execution) => execution.id === selectedId) ?? null;
  const returnTo =
    `/agents${searchParams.size ? `?${searchParams.toString()}` : ""}`;
  const agentNames = useMemo(
    () => [...new Set(allExecutions.map((item) => item.displayName))].sort(),
    [allExecutions],
  );
  const counts = useMemo(() => ({
    all: allExecutions.length,
    needsMe: countStatuses(allExecutions, STATUS_GROUPS.needs_me),
    running: countStatuses(allExecutions, "running"),
    completed: countStatuses(allExecutions, "completed"),
    failed: countStatuses(allExecutions, "failed"),
  }), [allExecutions]);
  const exactAttentionStatus = ["partial_success", "failed"].includes(filters.status)
    ? filters.status
    : "";
  const exactStoppedStatus = ["interrupted", "cancelled"].includes(filters.status)
    ? filters.status
    : "";

  const selectExecution = (executionId: string) => {
    setSelectedId(executionId);
    setPreviewOpen(true);
  };

  const setStatus = (status: string) => {
    setFilters((current) => ({ ...current, status }));
  };

  return (
    <section aria-label="任务运行" className="agent-run-center agent-run-center--friendly">
      <header className="agent-run-center__header">
        <div>
          <h1 id="agent-run-center-title">任务运行</h1>
          <p>查看 Agent 正在做什么，需要你处理的事项会优先显示。</p>
        </div>
        <div className="agent-run-center__header-actions">
          {workspace ? (
            <span className="agent-run-center__live" data-state={connectionStatus}>
              <Activity size={16} aria-hidden="true" />
              {connectionStatus === "connected" ? "实时更新" : "正在连接"}
            </span>
          ) : null}
          <Link className="agent-run-center__quality-link" to="/agents/evaluations">
            运行质量
            <ArrowUpRight size={15} aria-hidden="true" />
          </Link>
        </div>
      </header>

      {!workspace ? (
        <div className="agent-run-state">
          <Bot size={32} aria-hidden="true" />
          <strong>请先选择工作区后查看 Agent 运行。</strong>
          <p>运行中心会按当前工作区隔离运行和诊断数据。</p>
        </div>
      ) : query.isPending ? (
        <div className="agent-run-state" role="status">
          <LoaderCircle className="agent-run-state__spinner" size={28} />
          <strong>正在读取 Agent 运行</strong>
        </div>
      ) : query.isError ? (
        <div className="agent-run-state agent-run-state--error" role="alert">
          <AlertTriangle size={28} aria-hidden="true" />
          <strong>
            {query.error instanceof ObservabilityPayloadError
              ? query.error.message
              : "无法读取 Agent 运行"}
          </strong>
          <p>业务 Agent 不受影响，可以稍后重新打开此页面。</p>
        </div>
      ) : (
        <TaskWorkspace
          className={`agent-run-center__workspace${selected && previewOpen ? " has-preview" : ""}`}
          labelledBy="agent-run-center-title"
        >
          <div className="agent-run-center__main">
            {actionItems.length > 0 ? (
              <section className="agent-action-center" aria-labelledby="agent-action-center-title">
              <button
                className="agent-action-center__summary"
                type="button"
                aria-pressed={filters.status === "needs_me"}
                aria-label={`查看需要你处理的 ${actionItems.length} 个任务`}
                onClick={() => setStatus("needs_me")}
              >
                <div>
                  <span aria-hidden="true"><CircleAlert size={18} /></span>
                  <div>
                    <h2 id="agent-action-center-title">需要你处理</h2>
                    <p>这些任务需要确认、补充信息或查看失败原因。</p>
                  </div>
                </div>
                <strong>{actionItems.length}</strong>
              </button>
              <div className="agent-action-center__items">
                {actionItems.slice(0, 2).map((execution) => (
                  <article key={execution.id}>
                    <span
                      className="agent-action-center__icon"
                      data-tone={execution.status === "failed" ? "danger" : "warning"}
                      aria-hidden="true"
                    >
                      {execution.status === "failed"
                        ? <AlertTriangle size={18} />
                        : <CheckCircle2 size={18} />}
                    </span>
                    <div>
                      <strong>{executionTaskTitle(execution)}</strong>
                      <p>{executionResultSummary(execution)}</p>
                    </div>
                    <button type="button" onClick={() => selectExecution(execution.id)}>
                      {actionLabel(execution)}
                    </button>
                  </article>
                ))}
              </div>
              </section>
            ) : null}

            <section className="agent-run-panel" aria-labelledby="agent-run-list-title">
            <header className="agent-run-panel__toolbar">
              <div className="agent-run-panel__title">
                <h2 id="agent-run-list-title">所有任务</h2>
                <span>{counts.all}</span>
              </div>
              <nav className="agent-run-status-tabs" aria-label="任务状态">
                {[
                  ["", "全部", counts.all],
                  ["needs_me", "需要我", counts.needsMe],
                  ["running", "进行中", counts.running],
                  ["completed", "已完成", counts.completed],
                  ["failed", "失败", counts.failed],
                ].map(([value, label, count]) => (
                  <button
                    key={String(value)}
                    type="button"
                    aria-pressed={filters.status === value}
                    onClick={() => setStatus(String(value))}
                  >
                    {label}
                    <span>{count}</span>
                  </button>
                ))}
              </nav>
              <div className="agent-run-panel__tools">
                <label className="agent-run-filters__search">
                  <Search size={16} aria-hidden="true" />
                  <span className="sr-only">搜索运行</span>
                  <input
                    type="search"
                    aria-label="搜索运行"
                    placeholder="搜索任务"
                    value={filters.search}
                    onChange={(event) =>
                      setFilters((current) => ({
                        ...current,
                        search: event.target.value,
                      }))
                    }
                  />
                </label>
                <button
                  className="agent-run-filter-toggle"
                  type="button"
                  aria-expanded={filterPanelOpen}
                  aria-controls="agent-run-filters"
                  onClick={() => setFilterPanelOpen((open) => !open)}
                >
                  <SlidersHorizontal size={17} aria-hidden="true" />
                  筛选
                </button>
              </div>
            </header>

            {filterPanelOpen ? (
              <button
                className="agent-run-filter-scrim"
                type="button"
                aria-label="关闭运行筛选"
                onClick={() => setFilterPanelOpen(false)}
              />
            ) : null}
            <div
              id="agent-run-filters"
              className="agent-run-filters"
              role="region"
              aria-label="运行筛选"
              data-mobile-open={filterPanelOpen}
              hidden={!filterPanelOpen}
            >
              <header className="agent-run-filters__mobile-header">
                <strong>筛选任务</strong>
                <button
                  type="button"
                  aria-label="关闭运行筛选"
                  onClick={() => setFilterPanelOpen(false)}
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </header>
              <SelectControl
                containerClassName="agent-run-filters__select"
                icon={<Bot size={17} />}
                label="Agent 类型"
                aria-label="Agent"
                value={filters.agentName}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    agentName: event.target.value,
                  }))
                }
              >
                <option value="">全部 Agent</option>
                {agentNames.map((name) => <option key={name}>{name}</option>)}
              </SelectControl>
              <SelectControl
                containerClassName="agent-run-filters__select"
                icon={<Activity size={17} />}
                label="运行状态"
                aria-label="运行状态"
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    status: event.target.value,
                  }))
                }
              >
                <option value="">全部状态</option>
                <option value="needs_me">需要我处理</option>
                <option value="running">进行中</option>
                <option value="waiting">等待处理</option>
                <option value="completed">已完成</option>
                <option value="attention">需要关注</option>
                {exactAttentionStatus ? (
                  <option value={exactAttentionStatus}>
                    {exactAttentionStatus === "partial_success"
                      ? "需要关注 · 部分完成"
                      : "需要关注 · 失败"}
                  </option>
                ) : null}
                <option value="stopped">已停止</option>
                {exactStoppedStatus ? (
                  <option value={exactStoppedStatus}>
                    {exactStoppedStatus === "interrupted"
                      ? "已停止 · 暂停"
                      : "已停止 · 取消"}
                  </option>
                ) : null}
              </SelectControl>
              <label className="agent-run-filters__system">
                <input
                  type="checkbox"
                  checked={filters.includeSystemAgents}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      includeSystemAgents: event.target.checked,
                    }))
                  }
                />
                包含系统 Agent
              </label>
              <button
                className="agent-run-filters__done"
                type="button"
                onClick={() => setFilterPanelOpen(false)}
              >
                查看结果
              </button>
            </div>

            {allExecutions.length === 0 ? (
              <div className="agent-run-state">
                <Bot size={30} aria-hidden="true" />
                <strong>当前还没有 Agent 任务</strong>
                <p>启动题库整理、复习、画像或求职准备任务后会显示在这里。</p>
              </div>
            ) : executions.length === 0 ? (
              <div className="agent-run-state agent-run-state--compact">
                <Search size={28} aria-hidden="true" />
                <strong>没有找到符合条件的任务</strong>
                <button type="button" onClick={() => setFilters(EMPTY_FILTERS)}>
                  清除筛选
                </button>
              </div>
            ) : (
              <>
                <TaskWorkspace className="agent-run-workspace">
                  <TaskWorkspacePane
                    className="agent-run-workspace__list"
                    aria-label="任务列表"
                  >
                    <ExecutionList
                      executions={visibleExecutions}
                      selectedId={previewOpen ? selectedId : null}
                      onSelect={selectExecution}
                      returnTo={returnTo}
                    />
                  </TaskWorkspacePane>
                </TaskWorkspace>
                {totalPages > 1 ? (
                  <nav className="agent-run-pagination" aria-label="任务分页">
                    <button
                      type="button"
                      aria-label="上一页"
                      disabled={page === 1}
                      onClick={() => setPage((current) => Math.max(1, current - 1))}
                    >
                      <ChevronLeft size={16} aria-hidden="true" />
                    </button>
                    {Array.from({ length: totalPages }, (_, index) => index + 1)
                      .slice(Math.max(0, page - 2), Math.max(0, page - 2) + 3)
                      .map((pageNumber) => (
                        <button
                          key={pageNumber}
                          type="button"
                          aria-current={pageNumber === page ? "page" : undefined}
                          onClick={() => setPage(pageNumber)}
                        >
                          {pageNumber}
                        </button>
                      ))}
                    <button
                      type="button"
                      aria-label="下一页"
                      disabled={page === totalPages}
                      onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                    >
                      <ChevronRight size={16} aria-hidden="true" />
                    </button>
                  </nav>
                ) : null}
              </>
            )}
            </section>
          </div>
          {selected && previewOpen ? (
            <TaskWorkspacePane
              className="agent-run-center__preview agent-run-workspace__preview"
              aria-label="运行预览面板"
            >
              <ExecutionPreview
                execution={selected}
                onClose={() => setPreviewOpen(false)}
                returnTo={returnTo}
              />
            </TaskWorkspacePane>
          ) : null}
        </TaskWorkspace>
      )}
    </section>
  );
}
