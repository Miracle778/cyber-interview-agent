import { AlertTriangle, Download, X } from "lucide-react";
import { useState } from "react";
import { toActionableError } from "../../shared/api/errorAdvice";
import { Button } from "../../shared/ui/Button";
import {
  createTraceExport,
  traceExportDownloadUrl,
} from "./observabilityApi";
import type { TraceExport } from "./observabilityTypes";

interface TraceExportDialogProps {
  workspaceId: string;
  runId: string;
  advancedEnabled: boolean;
  onClose: () => void;
}

export function TraceExportDialog({
  workspaceId,
  runId,
  advancedEnabled,
  onClose,
}: TraceExportDialogProps) {
  const [includeBodies, setIncludeBodies] = useState(false);
  const [receipt, setReceipt] = useState<TraceExport | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function generate() {
    setPending(true);
    setError(null);
    try {
      setReceipt(await createTraceExport(workspaceId, runId, includeBodies));
    } catch (reason) {
      setError(reason);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="dialog-backdrop trace-export-backdrop" role="presentation">
      <section
        className="trace-export-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trace-export-dialog-title"
      >
        <header>
          <div>
            <h2 id="trace-export-dialog-title">导出诊断包</h2>
            <p>生成只属于当前工作区和本次运行的 ZIP。</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭">
            <X size={18} />
          </Button>
        </header>

        <p className="trace-export-dialog__privacy">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>
            <strong>请按私密资料保管</strong>
            <small>包含正文时，可能包含 Prompt、回答、Tool 参数和 Provider 原始响应。</small>
          </span>
        </p>

        <label className="trace-export-dialog__option">
          <input
            type="checkbox"
            aria-label="包含已保存正文"
            checked={includeBodies}
            disabled={!advancedEnabled || pending}
            onChange={(change) => setIncludeBodies(change.target.checked)}
          />
          <span>
            <strong>包含已保存正文</strong>
            <small>
              {advancedEnabled
                ? "未勾选时只导出安全元数据。"
                : "需先开启高级诊断；当前仍可导出安全元数据。"}
            </small>
          </span>
        </label>

        <dl>
          <div><dt>运行范围</dt><dd>仅当前运行</dd></div>
          <div><dt>正文</dt><dd>{includeBodies ? "包含" : "不包含"}</dd></div>
          <div><dt>密钥与凭据</dt><dd>始终排除</dd></div>
        </dl>

        {error ? (
          <p className="trace-export-dialog__error" role="alert">
            {toActionableError(error, "生成诊断包失败").message}
          </p>
        ) : null}

        {receipt ? (
          <p className="trace-export-dialog__receipt" role="status">
            <strong>诊断包已生成</strong>
            <a
              href={traceExportDownloadUrl(workspaceId, receipt.id)}
              download
            >
              <Download size={16} />
              下载 ZIP
            </a>
          </p>
        ) : null}

        <footer>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <button
            className="trace-export-dialog__generate"
            type="button"
            disabled={pending}
            onClick={() => void generate()}
          >
            {pending ? "正在生成…" : "生成诊断包"}
          </button>
        </footer>
      </section>
    </div>
  );
}
