import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, RotateCcw, Save, Workflow } from "lucide-react";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Button } from "../../shared/ui/Button";
import {
  getWorkspaceModelBindings,
  listProviders,
  replaceWorkspaceModelBindings,
} from "./settingsApi";
import type { ModelRole, ProviderResource } from "./providerTypes";

const ROLE_LABELS: Record<ModelRole, string> = {
  question_generation: "题目生成",
  answer_evaluation: "回答评估",
  report_summarization: "复习总结",
  agent_chat: "通用对话",
  profile_extraction: "简历信息整理",
  profile_assessment: "个人资料分析",
  job_analysis: "岗位分析",
  project_deep_dive: "项目深挖",
};

const ROLE_DESCRIPTIONS: Record<ModelRole, string> = {
  question_generation: "从资料中整理候选题",
  answer_evaluation: "评价回答并给出补充建议",
  report_summarization: "整理复习结果和阶段总结",
  agent_chat: "处理通用 Agent 会话",
  profile_extraction: "读取简历并整理结构化信息",
  profile_assessment: "生成个人资料完善建议",
  job_analysis: "从 JD 中识别岗位重点",
  project_deep_dive: "围绕真实项目连续追问",
};

const ROLE_GROUPS: Array<{
  title: string;
  description: string;
  roles: ModelRole[];
}> = [
  {
    title: "复习与题库",
    description: "负责题目整理、回答评价和复习总结",
    roles: ["question_generation", "answer_evaluation", "report_summarization"],
  },
  {
    title: "个人资料",
    description: "负责简历解析和个人资料完善建议",
    roles: ["profile_extraction", "profile_assessment"],
  },
  {
    title: "求职准备",
    description: "负责岗位要求分析和项目经历深挖",
    roles: ["job_analysis", "project_deep_dive"],
  },
  {
    title: "通用助手",
    description: "未归入专项流程的 Agent 对话",
    roles: ["agent_chat"],
  },
];

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
  onDirtyChange?: (dirty: boolean) => void;
}

export function ModelBindings({ workspaceId, refreshKey = 0, onBindingsChanged, onDirtyChange }: ModelBindingsProps) {
  const [providers, setProviders] = useState<ProviderResource[]>([]);
  const [bindings, setBindings] = useState<Record<ModelRole, string>>(EMPTY_BINDINGS);
  const [initialBindings, setInitialBindings] = useState<Record<ModelRole, string>>(EMPTY_BINDINGS);
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
        const next = { ...EMPTY_BINDINGS, ...loadedBindings.bindings };
        setBindings(next);
        setInitialBindings(next);
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
                label: `${provider.name} · ${model.displayName}`,
              }))
          : [],
      ),
    [providers],
  );
  const complete = Object.values(bindings).every((modelId) =>
    models.some((model) => model.id === modelId),
  );
  const configuredCount = Object.values(bindings).filter((modelId) =>
    models.some((model) => model.id === modelId),
  ).length;
  const dirty = (Object.keys(bindings) as ModelRole[]).some(
    (role) => bindings[role] !== initialBindings[role],
  );

  useEffect(() => {
    onDirtyChange?.(dirty);
    document.body.dataset.modelBindingsDirty = dirty ? "true" : "false";
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    globalThis.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      globalThis.removeEventListener("beforeunload", handleBeforeUnload);
      delete document.body.dataset.modelBindingsDirty;
    };
  }, [dirty, onDirtyChange]);

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
      const next = { ...EMPTY_BINDINGS, ...resource.bindings };
      setBindings(next);
      setInitialBindings(next);
      setSaved(true);
      onBindingsChanged?.();
    } catch (caught) {
      setError(toActionableError(caught, "保存模型绑定失败"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="model-bindings" aria-labelledby="model-bindings-title">
      <div className="model-bindings__header">
        <span className="model-bindings__icon" aria-hidden="true"><Workflow size={19} /></span>
        <div>
          <p className="settings-content__eyebrow">任务分配</p>
          <h3 id="model-bindings-title">任务使用的模型</h3>
          <p>每个工作区可以按任务选择不同模型，模型服务和密钥仍可全局复用。</p>
        </div>
      </div>
      {loading ? <p className="status-note">加载中…</p> : null}
      {!loading && models.length === 0 ? (
        <div className="settings-guidance" role="status">
          <p>没有可用于绑定的模型</p>
          <p>请先在上方添加模型服务，并完成连接测试。</p>
        </div>
      ) : null}
      <div className="model-binding-groups">
        {ROLE_GROUPS.map((group) => (
          <section className="model-binding-group" key={group.title}>
            <div className="model-binding-group__heading">
              <h4>{group.title}</h4>
              <p>{group.description}</p>
            </div>
            <div className="model-binding-group__rows">
              {group.roles.map((role) => (
                <div className="model-binding-row" key={role}>
                  <label htmlFor={`binding-${role}`}>
                    <strong>{ROLE_LABELS[role]}</strong>
                    <span>{ROLE_DESCRIPTIONS[role]}</span>
                  </label>
                  <select
                    id={`binding-${role}`}
                    aria-label={ROLE_LABELS[role]}
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
          </section>
        ))}
      </div>
      <div className="model-bindings__savebar" data-dirty={dirty}>
        <div className="model-bindings__save-status">
          {saved ? <CheckCircle2 size={16} aria-hidden="true" /> : null}
          <strong>{configuredCount}/8 已配置</strong>
          <span>{dirty ? "有未保存修改" : saved ? "配置已保存" : "当前配置已生效"}</span>
        </div>
        <div className="btn-row">
          <Button
            variant="ghost"
            disabled={!dirty || saving}
            onClick={() => {
              setBindings(initialBindings);
              setSaved(false);
            }}
          >
            <RotateCcw size={15} aria-hidden="true" />
            放弃修改
          </Button>
          <Button onClick={handleSave} loading={saving} disabled={!complete || !dirty || saving}>
            <Save size={16} aria-hidden="true" />
            保存配置
          </Button>
        </div>
      </div>
      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>错误：{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}
    </section>
  );
}
