import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Bot, CheckCircle2, Clock3, LoaderCircle, Search, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router-dom";
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

function matchesFilters(
  execution: ExecutionSummary,
  filters: ExecutionFilters,
) {
  if (filters.status && execution.status !== filters.status) return false;
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
  const agentNames = useMemo(
    () => [...new Set((query.data?.items ?? []).map((item) => item.displayName))].sort(),
    [query.data?.items],
  );
  const metrics = useMemo(() => {
    const running = executions.filter((item) => item.status === "running").length;
    const waiting = executions.filter((item) =>
      ["queued", "waiting_for_input", "waiting_for_approval"].includes(item.status)
    ).length;
    const completed = executions.filter((item) => item.status === "completed").length;
    const partial = executions.filter((item) => item.status === "partial_success").length;
    const failed = executions.filter((item) => item.status === "failed").length;
    const latencies = executions
      .map((item) => item.latencyMs)
      .filter((value): value is number => value !== null);
    const average =
      latencies.length > 0
        ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length)
        : null;
    return { running, waiting, completed, partial, failed, average };
  }, [executions]);
  const agentOverview = useMemo(() => {
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
  }, [executions]);

  return (
    <section aria-label="Agent 运行中心" className="agent-run-center">
      <header className="agent-run-center__header">
        <div>
          <h1>Agent 运行中心</h1>
          <p>统一查看项目内所有 Agent 的运行、异常、上下文与质量。</p>
        </div>
        {workspace ? (
          <span className="agent-run-center__live" data-state={connectionStatus}>
            <Activity size={16} aria-hidden="true" />
            {connectionStatus === "connected" ? "实时更新" : "正在连接"}
          </span>
        ) : null}
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
        <>
          <section className="agent-run-metrics" aria-label="运行汇总">
            <Metric icon={<Activity />} label="运行中" value={metrics.running} tone="primary" />
            <Metric icon={<Clock3 />} label="等待处理" value={metrics.waiting} tone="neutral" />
            <Metric icon={<CheckCircle2 />} label="今日完成" value={metrics.completed} tone="success" />
            <Metric icon={<AlertTriangle />} label="部分成功" value={metrics.partial} tone="warning" />
            <Metric icon={<XCircle />} label="失败" value={metrics.failed} tone="danger" />
            <Metric icon={<Clock3 />} label="平均耗时" value={formatDuration(metrics.average)} tone="neutral" />
          </section>

          {agentOverview.length > 0 ? (
            <section className="agent-overview" aria-label="Agent 概览">
              <header><h2>Agent 概览</h2><span>{agentOverview.length} 类</span></header>
              <div>
                {agentOverview.map((agent) => (
                  <article key={agent.name}>
                    <span aria-hidden="true"><Bot size={18} /></span>
                    <strong>{agent.name}</strong>
                    <small>
                      运行中 {agent.running} · 已完成 {agent.completed}
                      {agent.attention ? ` · 需关注 ${agent.attention}` : ""}
                    </small>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <div className="agent-run-filters" aria-label="运行筛选">
            <label>
              <span>Agent</span>
              <select
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
              </select>
            </label>
            <label>
              <span>状态</span>
              <select
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
                <option value="waiting_for_input">等待输入</option>
                <option value="waiting_for_approval">等待确认</option>
                <option value="completed">已完成</option>
                <option value="partial_success">部分成功</option>
                <option value="failed">失败</option>
                <option value="interrupted">已暂停</option>
                <option value="cancelled">已取消</option>
              </select>
            </label>
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
          </div>

          {executions.length === 0 ? (
            <div className="agent-run-state">
              <Bot size={30} aria-hidden="true" />
              <strong>当前还没有 Agent 运行记录</strong>
              <p>启动题库整理、复习、画像或求职准备任务后会显示在这里。</p>
            </div>
          ) : (
            <div className={`agent-run-workspace${selected ? " has-preview" : ""}`}>
              <ExecutionList
                executions={executions}
                selectedId={selectedId}
                onSelect={setSelectedId}
                returnTo={returnTo}
              />
              {selected ? (
                <ExecutionPreview
                  execution={selected}
                  onClose={() => setSelectedId(null)}
                  returnTo={returnTo}
                />
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Metric({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactElement;
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <article data-tone={tone}>
      <span aria-hidden="true">{icon}</span>
      <div><small>{label}</small><strong>{value}</strong></div>
    </article>
  );
}
