import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Clock3,
  Cpu,
  Database,
  ExternalLink,
  LoaderCircle,
  RotateCcw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { formatBeijingTime } from "../../shared/time";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { WorkspaceConfig } from "../settings/settingsApi";
import {
  getObservabilityExecution,
  listObservabilityExecutions,
  listObservabilityOperations,
  ObservabilityPayloadError,
} from "./observabilityApi";
import {
  formatCompactNumber,
  formatDuration,
  statusLabel,
} from "./ExecutionList";
import { OperationTree } from "./OperationTree";
import type { OperationSummary } from "./observabilityTypes";
import "./observability.css";


interface ExecutionTracePageProps {
  workspace: WorkspaceConfig | null;
}

const OPERATION_KIND_LABELS: Record<OperationSummary["kind"], string> = {
  execution: "完整运行",
  agent: "Agent 步骤",
  model: "模型调用",
  tool: "工具调用",
  graph: "流程节点",
};

export function ExecutionTracePage({ workspace }: ExecutionTracePageProps) {
  const { runId = "" } = useParams();
  const location = useLocation();
  const from = (location.state as { from?: unknown } | null)?.from;
  const returnTo =
    typeof from === "string" && from.startsWith("/agents")
      ? from
      : "/agents";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<"process" | "detail">("process");
  const executionQuery = useQuery({
    queryKey: ["agent-observability", "execution", workspace?.id, runId],
    enabled: Boolean(workspace && runId),
    queryFn: ({ signal }) =>
      getObservabilityExecution(workspace!.id, runId, signal),
  });
  const operationsQuery = useQuery({
    queryKey: ["agent-observability", "operations", workspace?.id, runId],
    enabled: Boolean(workspace && runId),
    queryFn: ({ signal }) =>
      listObservabilityOperations(workspace!.id, runId, signal),
  });
  const runIndexQuery = useQuery({
    queryKey: ["agent-observability", "execution-index", workspace?.id],
    enabled: Boolean(workspace),
    queryFn: ({ signal }) =>
      listObservabilityExecutions(
        workspace!.id,
        {
          search: "",
          status: "",
          agentName: "",
          includeSystemAgents: false,
        },
        signal,
      ),
  });
  const operations = operationsQuery.data ?? [];

  useEffect(() => {
    if (selectedId && operations.some((item) => item.id === selectedId)) return;
    setSelectedId(operations[0]?.id ?? null);
  }, [operations, selectedId]);

  const selected = useMemo(
    () => operations.find((operation) => operation.id === selectedId) ?? null,
    [operations, selectedId],
  );
  const linearFallback =
    operations.length > 1 &&
    operations.every((operation) => operation.parentOperationId === null);

  if (!workspace) {
    return (
      <section className="execution-trace-page" aria-label="高级运行详情">
        <h1>高级运行详情</h1>
        <div className="agent-run-state">
          <Bot size={30} aria-hidden="true" />
          <strong>请先选择工作区。</strong>
          <p>运行详情会按当前工作区隔离查询。</p>
        </div>
      </section>
    );
  }

  if (executionQuery.isPending || operationsQuery.isPending) {
    return (
      <section className="execution-trace-page" aria-label="高级运行详情">
        <div className="agent-run-state" role="status">
          <LoaderCircle className="agent-run-state__spinner" size={28} />
          <strong>正在读取运行详情</strong>
        </div>
      </section>
    );
  }

  if (executionQuery.isError || operationsQuery.isError || !executionQuery.data) {
    const error = executionQuery.error ?? operationsQuery.error;
    return (
      <section className="execution-trace-page" aria-label="高级运行详情">
        <div className="agent-run-state agent-run-state--error" role="alert">
          <AlertTriangle size={28} aria-hidden="true" />
          <strong>
            {error instanceof ObservabilityPayloadError
              ? error.message
              : "无法读取运行详情"}
          </strong>
          <Link to={returnTo}>返回运行中心</Link>
        </div>
      </section>
    );
  }

  const execution = executionQuery.data;
  const indexedExecutions =
    runIndexQuery.data?.items.some((item) => item.id === execution.id)
      ? runIndexQuery.data.items
      : [execution, ...(runIndexQuery.data?.items ?? [])];
  const traceWarning =
    execution.traceHealth === "missing" ||
    execution.traceHealth === "unavailable"
      ? "本次运行缺少高级诊断记录"
      : execution.traceHealth === "partial"
        ? "本次运行的诊断记录不完整"
        : null;

  return (
    <section className="execution-trace-page" aria-label="高级运行详情">
      <header className="execution-trace__header">
        <Link to={returnTo} aria-label="返回运行中心">
          <ArrowLeft size={18} aria-hidden="true" />
        </Link>
        <div>
          <span>{execution.displayName}</span>
          <h1>{execution.title}</h1>
          <p>
            {statusLabel(execution.status)}
            {" · "}
            {formatBeijingTime(execution.startedAt ?? execution.createdAt, true) ?? "—"}
          </p>
        </div>
        {execution.capabilities.includes("open_business") && execution.route ? (
          <a className="execution-trace__business-link" href={execution.route}>
            打开业务页面
            <ExternalLink size={15} aria-hidden="true" />
          </a>
        ) : null}
      </header>

      {traceWarning ? (
        <p className="execution-trace__warning">
          <AlertTriangle size={17} aria-hidden="true" />
          {traceWarning}
        </p>
      ) : null}
      {linearFallback ? (
        <p className="execution-trace__compatibility">
          历史诊断信息不完整，已按时间顺序展示。
        </p>
      ) : null}

      <ul className="execution-trace__metrics" aria-label="运行指标">
        <TraceMetric icon={<Clock3 />} label="总耗时" value={formatDuration(execution.latencyMs)} />
        <TraceMetric icon={<Cpu />} label="模型调用" value={String(execution.modelCallCount)} />
        <TraceMetric icon={<Database />} label="Token" value={formatCompactNumber(execution.totalTokens)} />
        <TraceMetric icon={<RotateCcw />} label="重试" value={String(execution.retryCount)} />
      </ul>

      <nav className="execution-trace__mobile-nav" aria-label="详情视图">
        <button
          type="button"
          aria-pressed={mobileView === "process"}
          onClick={() => setMobileView("process")}
        >
          执行过程
        </button>
        <button
          type="button"
          aria-pressed={mobileView === "detail"}
          onClick={() => setMobileView("detail")}
        >
          详情
        </button>
      </nav>

      <TaskWorkspace className="execution-trace__workspace">
        <TaskWorkspacePane className="execution-trace__index">
          <nav aria-label="运行索引">
            <header>
              <h2>运行索引</h2>
              <span>{indexedExecutions.length} 条</span>
            </header>
            <div className="execution-trace__index-list">
              {indexedExecutions.map((item) => (
                <Link
                  key={item.id}
                  to={`/agents/executions/${encodeURIComponent(item.id)}`}
                  state={{ from: returnTo }}
                  aria-current={item.id === execution.id ? "page" : undefined}
                >
                  <span>{item.displayName}</span>
                  <strong>{item.title}</strong>
                  <small>
                    {statusLabel(item.status)}
                    {" · "}
                    {formatBeijingTime(item.startedAt ?? item.createdAt, false) ?? "—"}
                  </small>
                </Link>
              ))}
            </div>
          </nav>
        </TaskWorkspacePane>

        <TaskWorkspacePane
          className="execution-trace__process"
          aria-label="执行过程面板"
          data-mobile-active={mobileView === "process"}
        >
          <header>
            <h2>执行过程</h2>
            <span>{operations.length} 个 Operation</span>
          </header>
          {operations.length > 0 ? (
            <OperationTree
              operations={operations}
              selectedId={selectedId}
              onSelect={(operationId) => {
                setSelectedId(operationId);
                setMobileView("detail");
              }}
            />
          ) : (
            <div className="execution-trace__empty">
              <Bot size={26} aria-hidden="true" />
              <strong>没有可用的执行过程记录</strong>
              <p>业务结果仍可正常查看，本页不会展示推测或伪造的步骤。</p>
            </div>
          )}
        </TaskWorkspacePane>

        <TaskWorkspacePane
          className="execution-trace__detail"
          aria-label="Operation 详情"
          data-mobile-active={mobileView === "detail"}
        >
          <header><h2>Operation 详情</h2></header>
          {selected ? (
            <>
              <div className="execution-trace__detail-title">
                <span>{OPERATION_KIND_LABELS[selected.kind]}</span>
                <strong>{selected.name}</strong>
              </div>
              <dl>
                <div><dt>状态</dt><dd>{statusLabel(selected.status)}</dd></div>
                <div><dt>耗时</dt><dd>{formatDuration(selected.latencyMs)}</dd></div>
                <div><dt>事件数</dt><dd>{selected.eventCount}</dd></div>
                <div><dt>重试</dt><dd>{selected.retryCount}</dd></div>
                {selected.agentRole ? <div><dt>Agent 角色</dt><dd>{selected.agentRole}</dd></div> : null}
                {selected.errorCode ? <div><dt>错误码</dt><dd>{selected.errorCode}</dd></div> : null}
              </dl>
              <div className="execution-trace__disclosure">
                <strong>安全摘要模式</strong>
                <p>完整内容需开启高级诊断</p>
                <small>默认不加载提示词、工具参数、原始事件正文或供应商载荷。</small>
              </div>
            </>
          ) : (
            <p className="execution-preview__empty">选择一个 Operation 查看安全摘要。</p>
          )}
        </TaskWorkspacePane>
      </TaskWorkspace>
    </section>
  );
}

function TraceMetric({
  icon,
  label,
  value,
}: {
  icon: React.ReactElement;
  label: string;
  value: string;
}) {
  return (
    <li>
      <span aria-hidden="true">{icon}</span>
      <div><small>{label}</small><strong>{value}</strong></div>
    </li>
  );
}
