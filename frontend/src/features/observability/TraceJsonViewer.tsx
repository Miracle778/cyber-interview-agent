import { Check, Clipboard, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";

interface TraceJsonViewerProps {
  content: string;
  eventType: string;
  complete: boolean;
  modelCatalog?: Record<string, TraceModelDescriptor>;
}

export interface TraceModelDescriptor {
  displayName: string;
  modelId: string;
  providerName: string;
}

interface ModelRequestPresentation {
  userContent: string;
  userContentLabel: "本次用户回答" | "发送给模型的内容";
  supplement: string | null;
  context: string | null;
  systemInstruction: string | null;
  modelId: string | null;
  modelSettings: unknown;
}

interface ModelResponsePresentation {
  structuredResult: unknown;
  textContent: string | null;
  durationMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
}

const RESPONSE_FIELD_LABELS: Record<string, string> = {
  covered_key_points: "已覆盖关键点",
  partial_key_points: "部分覆盖关键点",
  missing_key_points: "待完善关键点",
  evidence_by_point: "回答证据",
  follow_up_required: "需要继续回答",
  follow_up_prompt: "下一步提示",
  rating: "评价等级",
  score: "评分",
  summary: "结果摘要",
  feedback: "反馈",
  fact_conflict: "事实冲突",
  project_mastery: "项目掌握情况",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function messageContent(value: unknown): string | null {
  const message = asRecord(value);
  return typeof message?.content === "string" && message.content.trim()
    ? message.content.trim()
    : null;
}

function hasVisibleValue(value: unknown) {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  const record = asRecord(value);
  return record ? Object.keys(record).length > 0 : true;
}

function splitReviewPrompt(content: string) {
  const answerMarker = "\n用户回答：";
  const answerAt = content.indexOf(answerMarker);
  if (answerAt < 0) return null;
  const answerStart = answerAt + answerMarker.length;
  const supplementMarker = "\n补充回答：";
  const supplementAt = content.indexOf(supplementMarker, answerStart);
  return {
    context: content.slice(0, answerAt).trim() || null,
    answer: content.slice(
      answerStart,
      supplementAt >= 0 ? supplementAt : content.length,
    ).trim(),
    supplement: supplementAt >= 0
      ? content.slice(supplementAt + supplementMarker.length).trim() || null
      : null,
  };
}

function modelRequestPresentation(value: unknown): ModelRequestPresentation | null {
  const payload = asRecord(value);
  if (!payload || !Array.isArray(payload.messages)) return null;
  const contents = payload.messages
    .map(messageContent)
    .filter((item): item is string => item !== null);
  if (contents.length === 0) return null;

  const review = contents.map(splitReviewPrompt).find((item) => item !== null);
  const systemInstruction = messageContent(payload.system_message);
  const modelId = typeof payload.provider_model_id === "string"
    ? payload.provider_model_id
    : null;
  return {
    userContent: review?.answer || contents.join("\n\n"),
    userContentLabel: review ? "本次用户回答" : "发送给模型的内容",
    supplement: review?.supplement ?? null,
    context: review?.context ?? null,
    systemInstruction,
    modelId,
    modelSettings: hasVisibleValue(payload.model_settings)
      ? payload.model_settings
      : undefined,
  };
}

function findUsageMetadata(value: unknown): Record<string, unknown> | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findUsageMetadata(item);
      if (found) return found;
    }
    return null;
  }
  const record = asRecord(value);
  if (!record) return null;
  const direct = asRecord(record.usage_metadata);
  if (direct) return direct;
  for (const item of Object.values(record)) {
    const found = findUsageMetadata(item);
    if (found) return found;
  }
  return null;
}

function firstResponseText(value: unknown): string | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstResponseText(item);
      if (found) return found;
    }
    return null;
  }
  const record = asRecord(value);
  if (!record) return typeof value === "string" && value.trim() ? value.trim() : null;
  if (typeof record.content === "string" && record.content.trim()) {
    return record.content.trim();
  }
  return null;
}

function numericValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function modelResponsePresentation(value: unknown): ModelResponsePresentation | null {
  const payload = asRecord(value);
  if (!payload) return null;
  const response = asRecord(payload.response) ?? payload;
  const result = response.result;
  const usage = findUsageMetadata(result);
  const structuredResult = response.structured_response;
  const textContent = firstResponseText(result);
  if (structuredResult === undefined && !textContent) return null;
  return {
    structuredResult,
    textContent,
    durationMs: numericValue(payload.duration_ms),
    inputTokens: numericValue(usage?.input_tokens),
    outputTokens: numericValue(usage?.output_tokens),
    totalTokens: numericValue(usage?.total_tokens),
  };
}

function friendlyResponseLabel(key: string) {
  return RESPONSE_FIELD_LABELS[key] ?? key.replaceAll("_", " ");
}

function FriendlyResponseValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>无</span>;
  if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
  if (typeof value === "string" || typeof value === "number") {
    return <span>{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span>无</span>;
    return (
      <ul>
        {value.map((item, index) => (
          <li
            key={`${index}-${String(item)}`}
            data-value-kind={asRecord(item) ? "record" : "scalar"}
          >
            <FriendlyResponseValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  const record = asRecord(value);
  if (!record) return <span>{String(value)}</span>;
  return (
    <dl>
      {Object.entries(record).map(([key, item]) => (
        <div key={key}>
          <dt>{friendlyResponseLabel(key)}</dt>
          <dd><FriendlyResponseValue value={item} /></dd>
        </div>
      ))}
    </dl>
  );
}

function readableJsonString(value: string) {
  let result = "\"";
  for (const character of value) {
    if (character === "\n" || character === "\r" || character === "\t") {
      result += character;
    } else {
      result += JSON.stringify(character).slice(1, -1);
    }
  }
  return `${result}\"`;
}

function readableJson(value: unknown, depth = 0): string {
  const indent = "  ".repeat(depth);
  const childIndent = "  ".repeat(depth + 1);
  if (typeof value === "string") return readableJsonString(value);
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return `[\n${value
      .map((item) => `${childIndent}${readableJson(item, depth + 1)}`)
      .join(",\n")}\n${indent}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return "{}";
  return `{\n${entries
    .map(([key, item]) =>
      `${childIndent}${JSON.stringify(key)}: ${readableJson(item, depth + 1)}`)
    .join(",\n")}\n${indent}}`;
}

export function TraceJsonViewer({
  content,
  eventType,
  complete,
  modelCatalog = {},
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
  const formattedContent = parsed.failed
    ? content
    : readableJson(parsed.value);
  const requestPresentation = eventType === "model.request" && !parsed.failed
    ? modelRequestPresentation(parsed.value)
    : null;
  const responsePresentation = eventType === "model.response" && !parsed.failed
    ? modelResponsePresentation(parsed.value)
    : null;

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

  const rawViewer = (
    <div className="trace-json-viewer">
      <div className="trace-json-viewer__toolbar">
        <div role="group" aria-label="正文显示方式">
          <button type="button" aria-pressed={!raw} onClick={() => setRaw(false)}>
            格式化
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
        <pre aria-label="可读 JSON">{formattedContent}</pre>
      )}
    </div>
  );

  if (responsePresentation) {
    return (
      <div className="trace-model-response">
        {responsePresentation.structuredResult !== undefined ? (
          <section className="trace-model-response__result">
            <span>模型处理结果</span>
            <h3>结构化结果</h3>
            <FriendlyResponseValue value={responsePresentation.structuredResult} />
          </section>
        ) : null}

        {responsePresentation.textContent ? (
          <section className="trace-model-request__section">
            <h3>模型返回内容</h3>
            <p>{responsePresentation.textContent}</p>
          </section>
        ) : null}

        <dl className="trace-model-response__metrics">
          {responsePresentation.durationMs !== null ? (
            <div><dt>处理耗时</dt><dd>{responsePresentation.durationMs.toLocaleString()} 毫秒</dd></div>
          ) : null}
          {responsePresentation.inputTokens !== null ? (
            <div><dt>输入 Token</dt><dd>{responsePresentation.inputTokens.toLocaleString()}</dd></div>
          ) : null}
          {responsePresentation.outputTokens !== null ? (
            <div><dt>输出 Token</dt><dd>{responsePresentation.outputTokens.toLocaleString()}</dd></div>
          ) : null}
          {responsePresentation.totalTokens !== null ? (
            <div><dt>合计 Token</dt><dd>{responsePresentation.totalTokens.toLocaleString()}</dd></div>
          ) : null}
        </dl>

        <details className="trace-model-request__raw">
          <summary>原始事件 JSON</summary>
          {rawViewer}
        </details>
      </div>
    );
  }

  if (!requestPresentation) return rawViewer;

  const modelDescriptor = requestPresentation.modelId
    ? modelCatalog[requestPresentation.modelId]
    : undefined;

  return (
    <div className="trace-model-request">
      {requestPresentation.modelId || requestPresentation.modelSettings !== undefined ? (
        <details className="trace-model-request__details" open>
          <summary>使用模型与参数</summary>
          {modelDescriptor ? (
            <div className="trace-model-request__model">
              <strong>{modelDescriptor.displayName}</strong>
              <span>{modelDescriptor.providerName} · {modelDescriptor.modelId}</span>
            </div>
          ) : requestPresentation.modelId ? (
            <div className="trace-model-request__model">
              <strong>未找到对应的模型配置</strong>
              <span>技术配置 ID：{requestPresentation.modelId}</span>
            </div>
          ) : null}
          {requestPresentation.modelSettings !== undefined ? (
            <pre>{readableJson(requestPresentation.modelSettings)}</pre>
          ) : null}
        </details>
      ) : null}

      {requestPresentation.systemInstruction ? (
        <details className="trace-model-request__details" open>
          <summary>系统上下文</summary>
          <p>{requestPresentation.systemInstruction}</p>
        </details>
      ) : null}

      <details className="trace-model-request__details" open>
        <summary>模型输入上下文</summary>
        <div className="trace-model-request__input">
          <section className="trace-model-request__primary">
            <span>模型实际收到的内容</span>
            <h3>{requestPresentation.userContentLabel}</h3>
            <p>{requestPresentation.userContent}</p>
          </section>

          {requestPresentation.supplement ? (
            <section className="trace-model-request__section">
              <h3>补充回答</h3>
              <p>{requestPresentation.supplement}</p>
            </section>
          ) : null}

          {requestPresentation.context ? (
            <pre>{requestPresentation.context}</pre>
          ) : null}
        </div>
      </details>

      <details className="trace-model-request__raw">
        <summary>原始事件 JSON</summary>
        {rawViewer}
      </details>
    </div>
  );
}
