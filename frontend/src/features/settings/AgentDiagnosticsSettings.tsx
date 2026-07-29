import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, LockKeyhole, X } from "lucide-react";
import { toActionableError } from "../../shared/api/errorAdvice";
import { Button } from "../../shared/ui/Button";
import {
  getAgentDiagnosticsSettings,
  replaceAgentDiagnosticsSettings,
} from "./settingsApi";

const QUERY_KEY = ["agent-diagnostics-settings"] as const;

export function AgentDiagnosticsSettings() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getAgentDiagnosticsSettings,
  });
  const update = useMutation({
    mutationFn: replaceAgentDiagnosticsSettings,
    onSuccess: (resource) => {
      queryClient.setQueryData(QUERY_KEY, resource);
      void queryClient.invalidateQueries({
        queryKey: ["agent-observability"],
      });
      setConfirming(false);
    },
  });

  const enabled = settings.data?.advancedEnabled ?? false;
  const error = update.error
    ? toActionableError(update.error, "保存高级诊断设置失败")
    : settings.error
      ? toActionableError(settings.error, "读取高级诊断设置失败")
      : null;

  function toggle() {
    if (enabled) {
      update.mutate(false);
      return;
    }
    setConfirming(true);
  }

  return (
    <div className="agent-diagnostics-settings">
      <div className="agent-diagnostics-settings__summary">
        <span className="agent-diagnostics-settings__icon" aria-hidden="true">
          <LockKeyhole size={18} />
        </span>
        <div>
          <h4>高级诊断模式</h4>
          <p>
            按需查看本机保存的 Prompt、上下文、Tool 参数和 Provider 原始响应。
            Trace 捕获不会因关闭此开关而停止。
          </p>
        </div>
        <button
          type="button"
          className="agent-diagnostics-switch"
          role="switch"
          aria-label="高级诊断模式"
          aria-checked={enabled}
          disabled={settings.isLoading || update.isPending}
          onClick={toggle}
        >
          <span aria-hidden="true" />
          <span className="sr-only">{enabled ? "已开启" : "已关闭"}</span>
        </button>
      </div>

      <p className="agent-diagnostics-settings__boundary">
        仅在这台设备上生效；API key、Cookie、Authorization 和 secret
        不会因此被保存或展示。
      </p>

      {settings.isLoading ? (
        <p className="agent-diagnostics-settings__status" role="status">
          正在读取本地设置…
        </p>
      ) : null}

      {error ? (
        <div className="error-banner" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}

      {confirming ? (
        <div className="dialog-backdrop" role="presentation">
          <section
            className="agent-diagnostics-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="agent-diagnostics-dialog-title"
          >
            <header>
              <div>
                <h3 id="agent-diagnostics-dialog-title">
                  开启高级诊断模式
                </h3>
                <p>开启后，本机页面可能显示以下私有内容。</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label="关闭"
                onClick={() => setConfirming(false)}
              >
                <X size={18} aria-hidden="true" />
              </Button>
            </header>
            <ul>
              <li>简历、JD、回答、Prompt、Tool 参数与 Tool 结果</li>
              <li>模型请求、Provider 原始响应和结构化输出</li>
              <li>上下文选择、截断、压缩和 Offload 记录</li>
            </ul>
            <p className="agent-diagnostics-dialog__notice">
              仅展示 Provider 实际返回的数据，不推测模型思维过程。
            </p>
            <footer>
              <Button
                variant="ghost"
                onClick={() => setConfirming(false)}
              >
                取消
              </Button>
              <Button
                loading={update.isPending}
                onClick={() => update.mutate(true)}
              >
                确认并开启
              </Button>
            </footer>
          </section>
        </div>
      ) : null}
    </div>
  );
}
