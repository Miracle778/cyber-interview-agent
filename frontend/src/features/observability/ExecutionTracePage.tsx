import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CircleAlert,
  Clock3,
  Cpu,
  Database,
  Download,
  LoaderCircle,
  RotateCcw,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { getAgentDiagnosticsSettings, listProviders } from "../settings/settingsApi";
import {
  getObservabilityExecution,
  listObservabilityEvents,
  listObservabilityOperations,
  ObservabilityPayloadError,
} from "./observabilityApi";
import {
  formatCompactNumber,
  formatDuration,
  formatRunUpdatedAt,
  executionResultSummary,
  executionTaskTitle,
  statusLabel,
} from "./ExecutionList";
import { OperationTree } from "./OperationTree";
import { TraceEventInspector } from "./TraceEventInspector";
import { TraceExportDialog } from "./TraceExportDialog";
import {
  friendlyOperationName,
  executionStartPresentation,
  failureEventWasRecovered,
  isFailureEventType,
  operationWasRecovered,
  operationKindLabel,
  operationStatusLabel,
} from "./observabilityLabels";
import { executionBusinessDestination } from "./observabilityNavigation";
import type { ExecutionSummary } from "./observabilityTypes";
import "./observability.css";


interface ExecutionTracePageProps {
  workspace: WorkspaceConfig | null;
}

function failureGuidance(execution: ExecutionSummary) {
  if (
    ["question.curate", "question.revise"].includes(execution.graphId)
    && execution.errorCode === "curation_work_item_failed"
  ) {
    return {
      what: "有一项资料没有完成处理，题库整理因此提前停止。",
      impact: "已完成的模型响应和诊断记录仍然保留，但本次题目整理没有形成完整结果。",
      next: "返回这次整理会话查看已保留内容，再决定继续处理或重新整理。",
    };
  }
  if (execution.status === "partial_success") {
    return {
      what: "任务只完成了部分处理，仍有步骤没有成功结束。",
      impact: "已经生成的结果会保留；未完成部分需要确认后再继续。",
      next: "先回到原任务核对已有结果，再查看下方失败步骤定位原因。",
    };
  }
  return {
    what: "Agent 在处理过程中停止，本次任务没有生成完整结果。",
    impact: "失败前已经保存的业务结果和诊断记录仍然保留。",
    next: "先返回原任务查看保留结果；需要排查时再从下方执行过程查看失败位置。",
  };
}

export function ExecutionTracePage({ workspace }: ExecutionTracePageProps) {
  const { runId = "" } = useParams();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const from = (location.state as { from?: unknown } | null)?.from;
  const requestedReturnTo = searchParams.get("returnTo");
  const validReturnTo = (value: unknown): value is string => typeof value === "string" && (value.startsWith("/agents") || value.startsWith("/retrospectives"));
  const returnTo = validReturnTo(requestedReturnTo) ? requestedReturnTo : validReturnTo(from) ? from : "/agents";
  const returnLabel = returnTo.startsWith("/retrospectives") ? "返回面试复盘" : "返回运行中心";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<"process" | "detail">("process");
  const [exportOpen, setExportOpen] = useState(false);
  const [narrowScreen, setNarrowScreen] = useState(false);
  const defaultFailureSelectionRun = useRef<string | null>(null);
  const userSelectionRun = useRef<string | null>(null);
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
  const eventsQuery = useQuery({
    queryKey: ["agent-observability", "events", workspace?.id, runId],
    enabled: Boolean(workspace && runId),
    queryFn: ({ signal }) =>
      listObservabilityEvents(workspace!.id, runId, signal),
  });
  const diagnosticsQuery = useQuery({
    queryKey: ["agent-diagnostics-settings"],
    enabled: Boolean(workspace),
    queryFn: getAgentDiagnosticsSettings,
  });
  const providersQuery = useQuery({
    queryKey: ["providers"],
    enabled: Boolean(workspace && diagnosticsQuery.data?.advancedEnabled),
    queryFn: listProviders,
  });
  const operations = operationsQuery.data ?? [];
  const events = eventsQuery.data ?? [];
  const modelCatalog = useMemo(
    () => Object.fromEntries(
      (providersQuery.data ?? []).flatMap((provider) =>
        provider.models.map((model) => [
          model.id,
          {
            displayName: model.displayName,
            modelId: model.modelId,
            providerName: provider.name,
          },
        ]),
      ),
    ),
    [providersQuery.data],
  );

  useEffect(() => {
    if (selectedId && operations.some((item) => item.id === selectedId)) return;
    setSelectedId(operations[0]?.id ?? null);
  }, [operations, selectedId]);

  useEffect(() => {
    if (
      !["failed", "partial_success"].includes(executionQuery.data?.status ?? "")
      || eventsQuery.isPending
      || defaultFailureSelectionRun.current === runId
      || userSelectionRun.current === runId
    ) {
      return;
    }
    defaultFailureSelectionRun.current = runId;
    const failureEvent = [...events]
      .reverse()
      .find((event) => isFailureEventType(event.eventType));
    if (!failureEvent) return;
    setSelectedId(failureEvent.operationId);
    setSelectedEventId(failureEvent.eventId);
  }, [events, eventsQuery.isPending, executionQuery.data?.status, runId]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrowScreen(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  const selected = useMemo(
    () => operations.find((operation) => operation.id === selectedId) ?? null,
    [operations, selectedId],
  );
  const selectedEvent = useMemo(
    () => events.find((event) => event.eventId === selectedEventId) ?? null,
    [events, selectedEventId],
  );
  const selectedRecovered = useMemo(
    () => selectedEvent
      ? failureEventWasRecovered(selectedEvent, events)
      : selected
        ? operationWasRecovered(selected, events, operations)
        : false,
    [events, operations, selected, selectedEvent],
  );
  const selectedResume = useMemo(
    () => selectedEvent
      ? executionStartPresentation(selectedEvent, events) === "recovery"
      : false,
    [events, selectedEvent],
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
          <Link to={returnTo}>{returnLabel}</Link>
        </div>
      </section>
    );
  }

  const execution = executionQuery.data;
  const businessDestination = executionBusinessDestination(execution, returnTo);
  const needsRecovery = ["failed", "partial_success"].includes(execution.status);
  const guidance = needsRecovery ? failureGuidance(execution) : null;
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
        <Link to={returnTo} aria-label={returnLabel}>
          <ArrowLeft size={18} aria-hidden="true" />
        </Link>
        <div>
          <span>{execution.displayName}</span>
          <h1 title={execution.title}>{executionTaskTitle(execution)}</h1>
          <p>
            {statusLabel(execution.status)}
            {" · "}
            {needsRecovery ? "失败于 " : "更新于 "}
            {formatRunUpdatedAt(
              execution.finishedAt ?? execution.startedAt ?? execution.createdAt,
            )}
          </p>
        </div>
        <div className="execution-trace__actions">
          {execution.capabilities.includes("open_business") && businessDestination.to ? (
            <Link
              className="execution-trace__business-link"
              to={businessDestination.to}
              state={{ from: returnTo }}
            >
              {needsRecovery
                ? businessDestination.exact ? "返回任务处理" : "打开业务页面"
                : businessDestination.exact ? "查看业务结果" : "打开业务页面"}
            </Link>
          ) : null}
          {execution.capabilities.includes("manual_judge") ? (
            <Link
              className="execution-trace__quality-link"
              to={`/agents/evaluations?executionId=${encodeURIComponent(execution.id)}`}
            >
              检查运行质量
            </Link>
          ) : null}
          <button type="button" onClick={() => setExportOpen(true)}>
            <Download size={15} aria-hidden="true" />
            导出诊断包
          </button>
        </div>
      </header>

      {guidance ? (
        <section className="execution-trace__outcome" aria-label="失败处理建议">
          <header>
            <span aria-hidden="true"><CircleAlert size={20} /></span>
            <div>
              <h2>{execution.status === "partial_success" ? "这次任务只完成了一部分" : "这次任务没有完成"}</h2>
              <p>{executionResultSummary(execution)}</p>
            </div>
          </header>
          <div className="execution-trace__guidance">
            <article>
              <small>发生了什么</small>
              <p>{guidance.what}</p>
              {execution.errorCode ? <code>{execution.errorCode}</code> : null}
            </article>
            <article>
              <small>影响范围</small>
              <p>{guidance.impact}</p>
            </article>
            <article>
              <small>建议处理</small>
              <p>{guidance.next}</p>
            </article>
          </div>
        </section>
      ) : null}

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
        <TaskWorkspacePane
          className="execution-trace__process"
          aria-label="执行过程面板"
          data-mobile-active={mobileView === "process"}
        >
          <header>
            <h2>执行过程</h2>
            <span>{operations.length} 个步骤</span>
          </header>
          {operations.length > 0 ? (
            <OperationTree
              operations={operations}
              events={events}
              selectedId={selectedId}
              selectedEventId={selectedEventId}
              executionStatus={execution.status}
              onSelect={(operationId) => {
                userSelectionRun.current = runId;
                setSelectedId(operationId);
                setSelectedEventId(null);
                setMobileView("detail");
              }}
              onSelectEvent={(eventId) => {
                userSelectionRun.current = runId;
                const event = events.find((item) => item.eventId === eventId);
                setSelectedEventId(eventId);
                if (event) setSelectedId(event.operationId);
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
          aria-label="步骤详情"
          data-mobile-active={mobileView === "detail"}
        >
          <header>
            <h2>{selectedEvent ? "事件详情" : "步骤详情"}</h2>
          </header>
          {selectedEvent ? (
            <TraceEventInspector
              workspaceId={workspace.id}
              runId={runId}
              event={selectedEvent}
              advancedEnabled={diagnosticsQuery.data?.advancedEnabled ?? false}
              recovered={selectedRecovered}
              resumed={selectedResume}
              modelCatalog={modelCatalog}
              drawer={narrowScreen}
              onClose={() => {
                setSelectedEventId(null);
                setMobileView("process");
              }}
            />
          ) : selected ? (
            <>
              <div className="execution-trace__detail-title">
                <span>{operationKindLabel(selected.kind)}</span>
                <strong>{friendlyOperationName(selected)}</strong>
              </div>
              <dl>
                <div>
                  <dt>状态</dt>
                  <dd>
                    {operationStatusLabel(
                      selected.status,
                      execution.status,
                      selectedRecovered,
                    )
                      ?? statusLabel(selected.status)}
                  </dd>
                </div>
                <div><dt>耗时</dt><dd>{formatDuration(selected.latencyMs)}</dd></div>
                <div><dt>事件数</dt><dd>{selected.eventCount}</dd></div>
                <div><dt>重试</dt><dd>{selected.retryCount}</dd></div>
                {friendlyOperationName(selected) !== selected.name ? (
                  <div><dt>技术名称</dt><dd>{selected.name}</dd></div>
                ) : null}
                {selected.agentRole ? <div><dt>内部角色</dt><dd>{selected.agentRole}</dd></div> : null}
                {selected.errorCode ? <div><dt>错误码</dt><dd>{selected.errorCode}</dd></div> : null}
              </dl>
              <div className="execution-trace__disclosure">
                <strong>安全摘要模式</strong>
                <p>完整内容需开启高级诊断</p>
                <small>默认不加载提示词、工具参数、原始事件正文或供应商载荷。</small>
              </div>
            </>
          ) : (
            <p className="execution-preview__empty">选择一个步骤查看安全摘要。</p>
          )}
        </TaskWorkspacePane>
      </TaskWorkspace>
      {exportOpen ? (
        <TraceExportDialog
          workspaceId={workspace.id}
          runId={runId}
          advancedEnabled={diagnosticsQuery.data?.advancedEnabled ?? false}
          onClose={() => setExportOpen(false)}
        />
      ) : null}
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
