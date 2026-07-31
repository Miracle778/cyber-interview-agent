import { Check, Clipboard, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";

interface TraceJsonViewerProps {
  content: string;
  eventType: string;
  complete: boolean;
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
  const formattedContent = parsed.failed
    ? content
    : readableJson(parsed.value);

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
}
