import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Bot, CheckCircle2, Clock3, LoaderCircle, Search, SlidersHorizontal, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ExecutionList, formatDuration } from "./ExecutionList";
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


interface AgentRunCenterPageProps {
  workspace: WorkspaceConfig | null;
}

const EMPTY_FILTERS: ExecutionFilters = {
  search: "",
  status: "",
  agentName: "",
  includeSystemAgents: false,
};

const STATUS_GROUPS: Record<string, Set<string>> = {
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
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [liveById, setLiveById] = useState<Record<string, ExecutionSummary>>({});
  const previousWorkspaceId = useRef(workspace?.id);
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
      filters,
    ],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) =>
      listObservabilityExecutions(workspace!.id, filters, signal),
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    if (previousWorkspaceId.current === workspace?.id) return;
    previousWorkspaceId.current = workspace?.id;
    setSelectedId(null);
    setLiveById({});
    setFilters(EMPTY_FILTERS);
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

  const executions = useMemo(() => {
    const byId = new Map<string, ExecutionSummary>();
    for (const execution of query.data?.items ?? []) {
      byId.set(execution.id, liveById[execution.id] ?? execution);
    }
    for (const execution of Object.values(liveById)) {
      if (!byId.has(execution.id)) byId.set(execution.id, execution);
    }
    return [...byId.values()].filter((execution) =>
      matchesFilters(execution, filters)
    );
  }, [filters, liveById, query.data?.items]);

  useEffect(() => {
    if (selectedId && executions.some((item) => item.id === selectedId)) return;
    setSelectedId(executions[0]?.id ?? null);
  }, [executions, selectedId]);

  const selected =
    executions.find((execution) => execution.id === selectedId) ?? null;
  const returnTo =
    `/agents${searchParams.size ? `?${searchParams.toString()}` : ""}`;
  const agentNames = useMemo(() => {
    const summarized = Object.keys(query.data?.agentCounts ?? {});
    return (summarized.length
      ? summarized
      : [...new Set((query.data?.items ?? []).map((item) => item.displayName))]
    ).sort();
  }, [query.data?.agentCounts, query.data?.items]);
  const metrics = useMemo(() => {
    const fallbackCounts = executions.reduce<Record<string, number>>(
      (counts, item) => ({
        ...counts,
        [item.status]: (counts[item.status] ?? 0) + 1,
      }),
      {},
    );
    const statusCounts = Object.keys(query.data?.statusCounts ?? {}).length
      ? query.data!.statusCounts
      : fallbackCounts;
    const running = statusCounts.running ?? 0;
    const waiting = [...STATUS_GROUPS.waiting].reduce(
      (count, status) => count + (statusCounts[status] ?? 0),
      0,
    );
    const completed = statusCounts.completed ?? 0;
    const partial = statusCounts.partial_success ?? 0;
    const failed = statusCounts.failed ?? 0;
    const latencies = executions
      .map((item) => item.latencyMs)
      .filter((value): value is number => value !== null);
    const average =
      latencies.length > 0
        ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length)
        : null;
    return { running, waiting, completed, partial, failed, average };
  }, [executions, query.data]);
  const exactAttentionStatus = ["partial_success", "failed"].includes(filters.status)
    ? filters.status
    : "";
  const exactStoppedStatus = ["interrupted", "cancelled"].includes(filters.status)
    ? filters.status
    : "";
  const agentOverview = useMemo(() => {
    const serverCounts = query.data?.agentCounts ?? {};
    if (Object.keys(serverCounts).length > 0) {
      return Object.entries(serverCounts).map(([name, counts]) => ({
        name,
        running: counts.running ?? 0,
        completed: counts.completed ?? 0,
        attention:
          (counts.partial_success ?? 0) + (counts.failed ?? 0),
      }));
    }
    const groups = new Map<string, ExecutionSummary[]>();
    for (const execution of executions) {
      groups.set(execution.displayName, [
        ...(groups.get(execution.displayName) ?? []),
        execution,
      ]);
    }
    return [...groups.entries()].map(([name, items]) => ({
      name,
      running: items.filter((item) => item.status === "running").length,
      completed: items.filter((item) => item.status === "completed").length,
      attention: items.filter((item) =>
        ["failed", "partial_success"].includes(item.status)
      ).length,
    }));
  }, [executions, query.data?.agentCounts]);
  const toggleStatusFilter = (status: string) => {
    setFilters((current) => ({
      ...current,
      status: current.status === status ? "" : status,
    }));
  };

  return (
    <section aria-label="Agent 运行中心" className="agent-run-center">
      <header className="agent-run-center__header">
        <div>
          <h1 id="agent-run-center-title">Agent 运行中心</h1>
          <p>统一查看项目内所有 Agent 的运行、异常、上下文与质量。</p>
        </div>
        {workspace ? (
          <span className="agent-run-center__live" data-state={connectionStatus}>
            <Activity size={16} aria-hidden="true" />
            {connectionStatus === "connected" ? "实时更新" : "正在连接"}
          </span>
        ) : null}
        <nav className="agent-run-center__tabs" aria-label="Agent 工作区">
          <Link to="/agents" aria-current="page">运行中心</Link>
          <Link to="/agents/evaluations">质量评估</Link>
        </nav>
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
          className="agent-run-center__workspace"
          labelledBy="agent-run-center-title"
        >
          <ul className="agent-run-metrics" aria-label="运行汇总">
            <Metric
              icon={<Activity />}
              label="运行中"
              value={metrics.running}
              tone="primary"
              pressed={filters.status === "running"}
              onClick={() => toggleStatusFilter("running")}
            />
            <Metric
              icon={<Clock3 />}
              label="等待处理"
              value={metrics.waiting}
              tone="neutral"
              pressed={filters.status === "waiting"}
              onClick={() => toggleStatusFilter("waiting")}
            />
            <Metric
              icon={<CheckCircle2 />}
              label="已完成"
              value={metrics.completed}
              tone="success"
              pressed={filters.status === "completed"}
              onClick={() => toggleStatusFilter("completed")}
            />
            <Metric
              icon={<AlertTriangle />}
              label="部分成功"
              value={metrics.partial}
              tone="warning"
              pressed={filters.status === "partial_success"}
              onClick={() => toggleStatusFilter("partial_success")}
            />
            <Metric
              icon={<XCircle />}
              label="失败"
              value={metrics.failed}
              tone="danger"
              pressed={filters.status === "failed"}
              onClick={() => toggleStatusFilter("failed")}
            />
            <Metric icon={<Clock3 />} label="平均耗时" value={formatDuration(metrics.average)} tone="neutral" />
          </ul>

          {agentOverview.length > 0 ? (
            <section className="agent-overview" aria-label="Agent 概览">
              <header><h2>Agent 概览</h2><span>{agentOverview.length} 类</span></header>
              <div>
                {agentOverview.map((agent) => (
                  <button
                    key={agent.name}
                    type="button"
                    aria-pressed={filters.agentName === agent.name}
                    onClick={() => setFilters((current) => ({
                      ...current,
                      agentName: current.agentName === agent.name ? "" : agent.name,
                    }))}
                  >
                    <span aria-hidden="true"><Bot size={18} /></span>
                    <strong>{agent.name}</strong>
                    <small>
                      运行中 {agent.running} · 已完成 {agent.completed}
                      {agent.attention ? ` · 需关注 ${agent.attention}` : ""}
                    </small>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          <button
            className="agent-run-filter-toggle"
            type="button"
            aria-expanded={mobileFiltersOpen}
            aria-controls="agent-run-filters"
            onClick={() => setMobileFiltersOpen(true)}
          >
            <SlidersHorizontal size={17} aria-hidden="true" />
            筛选运行
          </button>
          {mobileFiltersOpen ? (
            <button
              className="agent-run-filter-scrim"
              type="button"
              aria-label="关闭运行筛选"
              onClick={() => setMobileFiltersOpen(false)}
            />
          ) : null}
          <div
            id="agent-run-filters"
            className="agent-run-filters"
            role="region"
            aria-label="运行筛选"
            data-mobile-open={mobileFiltersOpen}
          >
            <header className="agent-run-filters__mobile-header">
              <strong>筛选运行</strong>
              <button
                type="button"
                aria-label="关闭运行筛选"
                onClick={() => setMobileFiltersOpen(false)}
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
              <option value="running">运行中</option>
              <option value="waiting">等待处理</option>
              <option value="completed">已完成</option>
              <option value="attention">需关注</option>
              {exactAttentionStatus ? (
                <option value={exactAttentionStatus}>
                  {exactAttentionStatus === "partial_success"
                    ? "需关注 · 部分成功"
                    : "需关注 · 失败"}
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
            <label className="agent-run-filters__search">
              <Search size={16} aria-hidden="true" />
              <span className="sr-only">搜索运行</span>
              <input
                type="search"
                aria-label="搜索运行"
                placeholder="搜索会话、运行或业务对象"
                value={filters.search}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    search: event.target.value,
                  }))
                }
              />
            </label>
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
              onClick={() => setMobileFiltersOpen(false)}
            >
              查看结果
            </button>
          </div>

          {executions.length === 0 ? (
            <div className="agent-run-state">
              <Bot size={30} aria-hidden="true" />
              <strong>当前还没有 Agent 运行记录</strong>
              <p>启动题库整理、复习、画像或求职准备任务后会显示在这里。</p>
            </div>
          ) : (
            <TaskWorkspace className={`agent-run-workspace${selected ? " has-preview" : ""}`}>
              <TaskWorkspacePane
                className="agent-run-workspace__list"
                aria-label="Execution 列表"
              >
                <ExecutionList
                  executions={executions}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  returnTo={returnTo}
                />
              </TaskWorkspacePane>
              {selected ? (
                <TaskWorkspacePane
                  className="agent-run-workspace__preview"
                  aria-label="运行预览面板"
                >
                  <ExecutionPreview
                    execution={selected}
                    onClose={() => setSelectedId(null)}
                    returnTo={returnTo}
                  />
                </TaskWorkspacePane>
              ) : null}
            </TaskWorkspace>
          )}
        </TaskWorkspace>
      )}
    </section>
  );
}

function Metric({
  icon,
  label,
  value,
  tone,
  pressed,
  onClick,
}: {
  icon: ReactElement;
  label: string;
  value: number | string;
  tone: string;
  pressed?: boolean;
  onClick?: () => void;
}) {
  const content = (
    <>
      <span aria-hidden="true">{icon}</span>
      <div><small>{label}</small><strong>{value}</strong></div>
    </>
  );
  return (
    <li data-tone={tone}>
      {onClick ? (
        <button
          type="button"
          className="agent-run-metric"
          aria-label={`筛选${label}，${value} 条`}
          aria-pressed={pressed}
          onClick={onClick}
        >
          {content}
        </button>
      ) : (
        <div className="agent-run-metric">{content}</div>
      )}
    </li>
  );
}
