import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Save, Workflow } from "lucide-react";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import {
  getWorkspaceModelBindings,
  listProviders,
  replaceWorkspaceModelBindings,
} from "./settingsApi";
import type { ModelRole, ProviderResource } from "./providerTypes";

const ROLE_LABELS: Record<ModelRole, string> = {
  question_generation: "题目生成模型",
  answer_evaluation: "回答评估模型",
  report_summarization: "报告总结模型",
  agent_chat: "Agent 对话模型",
  profile_extraction: "简历结构化提取模型",
  profile_assessment: "画像评估模型",
  job_analysis: "岗位分析模型",
  project_deep_dive: "项目深挖模型",
};

const EMPTY_BINDINGS: Record<ModelRole, string> = {
  question_generation: "",
  answer_evaluation: "",
  report_summarization: "",
  agent_chat: "",
  profile_extraction: "",
  profile_assessment: "",
  job_analysis: "",
  project_deep_dive: "",
};

interface ModelBindingsProps {
  workspaceId: string;
  refreshKey?: number;
  onBindingsChanged?: () => void;
}

export function ModelBindings({ workspaceId, refreshKey = 0, onBindingsChanged }: ModelBindingsProps) {
  const [providers, setProviders] = useState<ProviderResource[]>([]);
  const [bindings, setBindings] = useState<Record<ModelRole, string>>(EMPTY_BINDINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ActionableError | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void Promise.all([listProviders(), getWorkspaceModelBindings(workspaceId)])
      .then(([loadedProviders, loadedBindings]) => {
        if (cancelled) return;
        setProviders(loadedProviders);
        setBindings({ ...EMPTY_BINDINGS, ...loadedBindings.bindings });
        setError(null);
      })
      .catch((caught) => {
        if (!cancelled) setError(toActionableError(caught, "加载模型绑定失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, refreshKey]);

  const models = useMemo(
    () =>
      providers.flatMap((provider) =>
        provider.enabled && provider.hasSecret
          ? provider.models
              .filter((model) => model.enabled)
              .map((model) => ({
                id: model.id,
                label: `${provider.name} / ${model.displayName} (${model.modelId})`,
              }))
          : [],
      ),
    [providers],
  );
  const complete = Object.values(bindings).every((modelId) =>
    models.some((model) => model.id === modelId),
  );

  async function handleSave() {
    if (!complete) {
      setError(toActionableError(new Error("请为八种用途选择可用模型"), "保存模型绑定失败"));
      return;
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const resource = await replaceWorkspaceModelBindings(workspaceId, bindings);
      setBindings({ ...EMPTY_BINDINGS, ...resource.bindings });
      setSaved(true);
      onBindingsChanged?.();
    } catch (caught) {
      setError(toActionableError(caught, "保存模型绑定失败"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="模型用途绑定" icon={<Workflow size={18} aria-hidden="true" />}>
      {loading ? <p className="status-note">加载中…</p> : null}
      {!loading && models.length === 0 ? (
        <div className="settings-guidance" role="status">
          <p>没有可用于绑定的模型</p>
          <p>请先在上方 Provider 中添加模型并完成连接测试。</p>
        </div>
      ) : null}
      <div className="binding-grid">
        {(Object.keys(ROLE_LABELS) as ModelRole[]).map((role) => (
          <div className="field" key={role}>
            <label className="field__label" htmlFor={`binding-${role}`}>
              {ROLE_LABELS[role]}
            </label>
            <select
              id={`binding-${role}`}
              className="field__input"
              value={bindings[role]}
              disabled={loading || models.length === 0}
              onChange={(event) => {
                setSaved(false);
                setBindings((current) => ({ ...current, [role]: event.target.value }));
              }}
            >
              <option value="">请选择模型</option>
              {models.map((model) => (
                <option value={model.id} key={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <div className="btn-row">
        <Button onClick={handleSave} loading={saving} disabled={!complete || saving}>
          <Save size={16} aria-hidden="true" />
          保存模型绑定
        </Button>
        {saved ? <span className="status-note status-note--inline">已保存</span> : null}
      </div>
      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>错误：{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}
    </Card>
  );
}
