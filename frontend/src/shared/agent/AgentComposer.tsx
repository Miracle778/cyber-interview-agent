import { type FormEvent, useEffect, useRef, useState } from "react";
import { ChevronDown, Send, SlidersHorizontal, Square } from "lucide-react";
import { Button } from "../ui/Button";

export type AgentReasoningEffort = "none" | "low" | "medium" | "high";

const reasoningLabels: Record<AgentReasoningEffort, string> = {
  none: "标准",
  low: "较低",
  medium: "中等",
  high: "较高",
};

interface AgentComposerProps {
  busy: boolean;
  stopping: boolean;
  modelId: string;
  models: { id: string; label: string }[];
  reasoningEffort: AgentReasoningEffort;
  placeholder: string;
  promptToFill?: string | null;
  onPromptFilled?: () => void;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (effort: AgentReasoningEffort) => void;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function AgentComposer({
  busy,
  stopping,
  modelId,
  models,
  reasoningEffort,
  placeholder,
  promptToFill,
  onPromptFilled,
  onModelChange,
  onReasoningEffortChange,
  onSend,
  onStop,
}: AgentComposerProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (promptToFill) {
      setText(promptToFill);
      onPromptFilled?.();
      textareaRef.current?.focus();
    }
  }, [onPromptFilled, promptToFill]);
  useEffect(() => {
    if (wasBusy.current && !busy) textareaRef.current?.focus();
    wasBusy.current = busy;
  }, [busy]);
  function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    onSend(value);
  }
  const selectedModel = models.find((model) => model.id === modelId)?.label ?? "工作区默认模型";
  return (
    <form className="agent-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor="agent-composer-message">发送给画像助手</label>
      <textarea
        ref={textareaRef}
        id="agent-composer-message"
        rows={1}
        value={text}
        disabled={busy}
        placeholder={placeholder}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="agent-composer__toolbar">
        <details className="agent-composer__settings">
          <summary onClick={(event) => { if (busy) event.preventDefault(); }}>
            <SlidersHorizontal size={16} />
            <span>{selectedModel} · {reasoningLabels[reasoningEffort]}</span>
            <ChevronDown size={14} />
          </summary>
          <div>
            <label htmlFor="agent-composer-model">本次执行模型</label>
            <select id="agent-composer-model" value={modelId} disabled={busy} onChange={(event) => onModelChange(event.target.value)}>
              <option value="">使用工作区默认模型</option>
              {models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
            </select>
            <label htmlFor="agent-composer-reasoning">思考强度</label>
            <select id="agent-composer-reasoning" value={reasoningEffort} disabled={busy} onChange={(event) => onReasoningEffortChange(event.target.value as AgentReasoningEffort)}>
              {Object.entries(reasoningLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
        </details>
        <small>Shift+Enter 换行</small>
        {busy
          ? <Button type="button" variant="danger" disabled={stopping} onClick={onStop}><Square size={15} />{stopping ? "正在停止…" : "停止"}</Button>
          : <Button type="submit" disabled={!text.trim()} aria-label="发送"><Send size={17} /></Button>}
      </div>
    </form>
  );
}
