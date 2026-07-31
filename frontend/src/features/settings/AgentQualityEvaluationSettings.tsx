import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical } from "lucide-react";
import { toActionableError } from "../../shared/api/errorAdvice";
import {
  getAgentQualityEvaluationSettings,
  replaceAgentQualityEvaluationSettings,
} from "./settingsApi";

const QUERY_KEY = ["agent-quality-evaluation-settings"] as const;

export function AgentQualityEvaluationSettings() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getAgentQualityEvaluationSettings,
  });
  const update = useMutation({
    mutationFn: (captureRegressionInputs: boolean) => {
      const current = settings.data;
      if (!current) throw new Error("质量评估设置尚未加载");
      return replaceAgentQualityEvaluationSettings({
        enabled: current.enabled,
        captureRegressionInputs,
        automaticSamplePercent: current.automaticSamplePercent,
        automaticDailyCap: current.automaticDailyCap,
        judgeProviderModelId: current.judgeProviderModelId,
      });
    },
    onSuccess: (resource) => {
      queryClient.setQueryData(QUERY_KEY, resource);
    },
  });
  const enabled = settings.data?.captureRegressionInputs ?? false;
  const error = update.error
    ? toActionableError(update.error, "保存回归输入设置失败")
    : settings.error
      ? toActionableError(settings.error, "读取回归输入设置失败")
      : null;

  function toggle() {
    if (!enabled) {
      const confirmed = window.confirm(
        "开启后，新运行的受支持 Agent 会在本机保存执行前数据库、会话状态和材料副本，用于隔离回归。不会上传到 Judge，但会占用本机磁盘。确认开启吗？",
      );
      if (!confirmed) return;
    }
    update.mutate(!enabled);
  }

  return (
    <div className="agent-diagnostics-settings">
      <div className="agent-diagnostics-settings__summary">
        <span className="agent-diagnostics-settings__icon" aria-hidden="true">
          <FlaskConical size={18} />
        </span>
        <div>
          <h4>记录可回归输入</h4>
          <p>
            在 Agent 真正执行前冻结本机任务数据和会话状态，之后可让来源配置与当前配置在两个隔离沙箱中重新运行。
          </p>
        </div>
        <button
          type="button"
          className="agent-diagnostics-switch"
          role="switch"
          aria-label="记录可回归输入"
          aria-checked={enabled}
          disabled={settings.isLoading || update.isPending}
          onClick={toggle}
        >
          <span aria-hidden="true" />
          <span className="sr-only">{enabled ? "已开启" : "已关闭"}</span>
        </button>
      </div>
      <p className="agent-diagnostics-settings__boundary">
        默认关闭。只影响开启后的新运行；历史运行没有执行前快照时仍只能做历史结果复检。
      </p>
      {error ? (
        <div className="error-banner" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}
    </div>
  );
}
