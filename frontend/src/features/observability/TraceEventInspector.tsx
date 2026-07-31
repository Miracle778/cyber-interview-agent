import { AlertTriangle, LoaderCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toActionableError } from "../../shared/api/errorAdvice";
import { getTraceEventContent } from "./observabilityApi";
import { TraceJsonViewer } from "./TraceJsonViewer";
import { friendlyEventName } from "./observabilityLabels";
import type { TraceEventContent, TraceEventSummary } from "./observabilityTypes";

interface TraceEventInspectorProps {
  workspaceId: string;
  runId: string;
  event: TraceEventSummary | null;
  advancedEnabled: boolean;
  drawer?: boolean;
  onClose?: () => void;
}

function eventFamily(eventType: string) {
  if (eventType === "model.request") return "请求";
  if (eventType === "model.response") return "响应";
  if (eventType.startsWith("tool.")) return "Tool";
  if (eventType.startsWith("context.")) return "上下文";
  return "配置";
}

export function TraceEventInspector({
  workspaceId,
  runId,
  event,
  advancedEnabled,
  drawer = false,
  onClose,
}: TraceEventInspectorProps) {
  const [pages, setPages] = useState<TraceEventContent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setPages([]);
    setError(null);
    if (!event || !advancedEnabled || event.bodyState !== "available") return;
    const controller = new AbortController();
    setLoading(true);
    void getTraceEventContent(
      workspaceId,
      runId,
      event.eventId,
      0,
      controller.signal,
    ).then((page) => {
      setPages([page]);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [advancedEnabled, event, runId, workspaceId]);

  const nextOffset = pages.at(-1)?.nextOffset ?? null;
  const complete = pages.at(-1)?.complete ?? false;
  const content = pages.map((page) => page.content).join("");
  const reasoning = pages.find((page) => page.reasoning !== undefined)?.reasoning;

  async function loadMore() {
    if (!event || nextOffset === null) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await getTraceEventContent(
        workspaceId,
        runId,
        event.eventId,
        nextOffset,
      );
      setPages((current) => [...current, page]);
    } catch (reason) {
      setError(reason);
    } finally {
      setLoadingMore(false);
    }
  }

  const commonProps = drawer
    ? {
        role: "dialog" as const,
        "aria-modal": true,
        "aria-label": "事件详情",
      }
    : {
        role: "region" as const,
        "aria-label": "事件详情",
      };

  return (
    <section
      {...commonProps}
      className={`trace-event-inspector${drawer ? " trace-event-inspector--drawer" : ""}`}
    >
      <header>
        <div>
          <span>{event ? eventFamily(event.eventType) : "事件正文"}</span>
          <h2>{event ? friendlyEventName(event.eventType) : "选择一个事件"}</h2>
          {event ? <small>{event.eventType}</small> : null}
        </div>
        {drawer && onClose ? (
          <button type="button" onClick={onClose} aria-label="关闭事件详情">
            <X size={18} />
          </button>
        ) : null}
      </header>

      {!event ? (
        <p className="trace-event-inspector__empty">
          从执行过程里选择一个事件，正文才会按需加载。
        </p>
      ) : (
        <>
          {event.eventType.includes("failed") || event.eventType.includes("error") ? (
            <section className="trace-event-inspector__failure">
              <AlertTriangle size={18} aria-hidden="true" />
              <div>
                <strong>这一步没有完成</strong>
                <p>下面是系统保存的错误记录，可用于确认失败位置或导出诊断。</p>
              </div>
            </section>
          ) : null}
          <dl className="trace-event-inspector__metadata">
            <div><dt>序号</dt><dd>{event.sequence}</dd></div>
            <div><dt>正文大小</dt><dd>{event.byteLength.toLocaleString()} B</dd></div>
          </dl>
          <p className="trace-event-inspector__provider-boundary">
            仅展示 Provider 实际返回的数据，不推测模型思维过程。
          </p>

          {event.bodyState !== "available" ? (
            <div className="execution-trace__disclosure">
              <strong>正文已按保留策略移除</strong>
              <p>事件类型、时间、大小和完整性哈希仍保留；元数据索引不能恢复正文。</p>
            </div>
          ) : null}

          {!advancedEnabled && event.bodyState === "available" ? (
            <div className="execution-trace__disclosure">
              <strong>完整内容需开启高级诊断</strong>
              <p>可在设置 → 诊断中开启；关闭状态不会请求事件正文。</p>
            </div>
          ) : null}

          {event.bodyState === "available" && event.byteLength > 200 * 1024 ? (
            <p className="trace-event-inspector__size-warning">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                <strong>正文超过 200 KB</strong>
                将分段加载以避免阻塞页面。
              </span>
            </p>
          ) : null}

          {loading ? (
            <p className="trace-event-inspector__loading" role="status">
              <LoaderCircle size={16} className="agent-run-state__spinner" />
              正在读取已保存正文…
            </p>
          ) : null}

          {error ? (
            <p className="trace-event-inspector__error" role="alert">
              {toActionableError(error, "读取事件正文失败").message}
            </p>
          ) : null}

          {pages.length > 0 ? (
            <TraceJsonViewer
              content={content}
              eventType={event.eventType}
              complete={complete}
            />
          ) : null}

          {nextOffset !== null ? (
            <button
              className="trace-event-inspector__load-more"
              type="button"
              disabled={loadingMore}
              onClick={() => void loadMore()}
            >
              {loadingMore ? "正在加载…" : "继续加载"}
            </button>
          ) : null}

          {reasoning !== undefined ? (
            <section className="trace-event-inspector__reasoning">
              <h3>Provider 返回的 reasoning</h3>
              <pre>
                {typeof reasoning === "string"
                  ? reasoning
                  : JSON.stringify(reasoning, null, 2)}
              </pre>
            </section>
          ) : null}
        </>
      )}
    </section>
  );
}
