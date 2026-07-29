import { Check, Clipboard, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";

interface TraceJsonViewerProps {
  content: string;
  eventType: string;
  complete: boolean;
}

interface TraceSection {
  label: string;
  value: unknown;
}

const MODEL_PARAMETER_KEYS = new Set([
  "temperature",
  "top_p",
  "max_tokens",
  "max_output_tokens",
  "model",
  "response_format",
  "response_schema",
]);

function objectEntries(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function select(record: Record<string, unknown>, keys: string[]) {
  return Object.fromEntries(
    keys.filter((key) => key in record).map((key) => [key, record[key]]),
  );
}

function hasValues(value: Record<string, unknown>) {
  return Object.keys(value).length > 0;
}

function sectionsFor(eventType: string, value: unknown): TraceSection[] {
  const record = objectEntries(value);
  if (!record) return [{ label: "事件正文", value }];

  if (eventType === "model.request") {
    const parameters = Object.fromEntries(
      Object.entries(record).filter(([key]) => MODEL_PARAMETER_KEYS.has(key)),
    );
    return [
      { label: "请求消息", value: record.messages ?? record.prompt ?? record.input },
      { label: "工具定义", value: record.tools },
      { label: "模型参数", value: parameters },
      {
        label: "请求上下文",
        value: select(record, ["system_prompt", "context", "instructions"]),
      },
    ].filter((section) => section.value !== undefined &&
      (!objectEntries(section.value) || hasValues(objectEntries(section.value)!)));
  }

  if (eventType === "model.response") {
    const providerResponse = objectEntries(record.response);
    const response = providerResponse ?? record;
    return [
      {
        label: "结构化响应",
        value: response.structured_response ?? response.parsed,
      },
      {
        label: "原始响应",
        value: response.raw_response ?? response.result ?? response.output ?? response.content,
      },
      {
        label: "响应元数据",
        value: {
          ...select(record, ["duration_ms", "latency_ms"]),
          ...select(response, ["model", "finish_reason", "response_id"]),
        },
      },
      {
        label: "Token 用量",
        value: response.usage ??
          record.usage ??
          select(response, ["input_tokens", "output_tokens", "total_tokens"]),
      },
      {
        label: "错误",
        value: response.error ?? record.error ?? record.error_code,
      },
    ].filter((section) => section.value !== undefined &&
      (!objectEntries(section.value) || hasValues(objectEntries(section.value)!)));
  }

  if (eventType.startsWith("tool.")) {
    return [
      {
        label: eventType.endsWith(".request") ? "Tool 参数" : "Tool 结果",
        value: eventType.endsWith(".request")
          ? record.arguments ?? record.args ?? record.input ?? record
          : record.result ?? record.output ?? record.error ?? record,
      },
      {
        label: "Tool 元数据",
        value: select(record, ["tool_name", "duration_ms", "retry_count", "error_code"]),
      },
    ].filter((section) =>
      !objectEntries(section.value) || hasValues(objectEntries(section.value)!));
  }

  return [{ label: "事件正文", value }];
}

function renderValue(value: unknown) {
  return typeof value === "string"
    ? value
    : JSON.stringify(value, null, 2);
}

export function TraceJsonViewer({
  content,
  eventType,
  complete,
}: TraceJsonViewerProps) {
  const [raw, setRaw] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const parsed = useMemo(() => {
    if (!complete) return { value: null, failed: false };
    try {
      return { value: JSON.parse(content) as unknown, failed: false };
    } catch {
      return { value: content, failed: true };
    }
  }, [complete, content]);
  const sections = useMemo(
    () => sectionsFor(eventType, parsed.value),
    [eventType, parsed.value],
  );

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(content);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }

  if (!complete) {
    return (
      <pre className="trace-json-viewer__partial" aria-label="已加载正文片段">
        {content}
      </pre>
    );
  }

  return (
    <div className="trace-json-viewer">
      <div className="trace-json-viewer__toolbar">
        <div role="group" aria-label="正文显示方式">
          <button type="button" aria-pressed={!raw} onClick={() => setRaw(false)}>
            分段
          </button>
          <button type="button" aria-pressed={raw} onClick={() => setRaw(true)}>
            原文
          </button>
        </div>
        <button type="button" onClick={() => void copy()} aria-label="复制正文">
          {copyStatus === "copied" ? <Check size={15} /> : <Clipboard size={15} />}
          复制
        </button>
        {copyStatus !== "idle" ? (
          <span role="status">
            {copyStatus === "copied" ? "已复制" : "复制失败"}
          </span>
        ) : null}
      </div>

      {parsed.failed ? (
        <p className="trace-json-viewer__warning">
          <TriangleAlert size={15} aria-hidden="true" />
          正文不是可解析的 JSON，已按原文显示。
        </p>
      ) : null}

      {raw || parsed.failed ? (
        <pre>{content}</pre>
      ) : (
        <div className="trace-json-viewer__sections">
          {sections.map((section) => (
            <section key={section.label}>
              <h3>{section.label}</h3>
              <pre>{renderValue(section.value)}</pre>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
