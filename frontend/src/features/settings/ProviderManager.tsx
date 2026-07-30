import { useEffect, useState } from "react";
import { AlertCircle, ChevronDown, FlaskConical, Pencil, Plus, Server, Trash2, X } from "lucide-react";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { Field } from "../../shared/ui/Field";
import { SelectControl } from "../../shared/ui/SelectControl";
import { ApiError } from "../../shared/api/client";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import {
  createProvider,
  createProviderModel,
  deleteProvider,
  deleteProviderModel,
  listProviders,
  testProviderModel,
  updateProvider,
  updateProviderModel,
} from "./settingsApi";
import type {
  CreateProviderCommand,
  ProviderConnectivityStatus,
  ProviderFormat,
  ProviderModelResource,
  ProviderResource,
  UpdateProviderCommand,
  UpdateProviderModelCommand,
} from "./providerTypes";

type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

const STATUS_LABEL: Record<ProviderConnectivityStatus, string> = {
  unknown: "未测试",
  ok: "已连接",
  secret_missing: "缺少密钥",
  auth_failed: "认证失败",
  model_not_found: "模型不存在",
  rate_limited: "频率受限",
  timeout: "超时",
  network_error: "网络错误",
  protocol_error: "协议错误",
};

const STATUS_TONE: Record<ProviderConnectivityStatus, BadgeTone> = {
  unknown: "neutral",
  ok: "success",
  secret_missing: "warning",
  auth_failed: "danger",
  model_not_found: "danger",
  rate_limited: "warning",
  timeout: "warning",
  network_error: "warning",
  protocol_error: "danger",
};

const FORMAT_LABEL: Record<ProviderFormat, string> = {
  "openai-compatible": "OpenAI 兼容",
  "anthropic-compatible": "Anthropic 兼容",
};

const UNBIND_ADVICE = "请先移除各工作区中的任务模型分配，再删除";

function isResourceInUse(caught: unknown): caught is ApiError {
  return caught instanceof ApiError && caught.code === "resource_in_use";
}

interface ProviderManagerProps {
  onProvidersChanged?: () => void;
}

export function ProviderManager({ onProvidersChanged }: ProviderManagerProps = {}) {
  const [providers, setProviders] = useState<ProviderResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ActionableError | null>(null);

  const [name, setName] = useState("");
  const [apiFormat, setApiFormat] = useState<ProviderFormat>("openai-compatible");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [createExpanded, setCreateExpanded] = useState(false);
  const [expandedProviderId, setExpandedProviderId] = useState<string | null>(null);

  useEffect(() => {
    void loadProviders();
  }, []);

  async function loadProviders() {
    setLoading(true);
    try {
      setProviders(await listProviders());
      setError(null);
    } catch (caught) {
      setError(toActionableError(caught, "加载模型服务失败"));
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    setError(null);
    if (!name.trim() || !baseUrl.trim() || !apiKey.trim()) {
      setError(toActionableError(new Error("请填写名称、Base URL 和 API Key"), "创建模型服务失败"));
      return;
    }
    setSaving(true);
    try {
      const command: CreateProviderCommand = {
        name: name.trim(),
        apiFormat,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
      };
      const created = await createProvider(command);
      setProviders((prev) => [...prev, created]);
      onProvidersChanged?.();
      // API key lives only in short-lived state; clear immediately on success.
      setName("");
      setBaseUrl("");
      setApiKey("");
      setCreateExpanded(false);
    } catch (caught) {
      setError(toActionableError(caught, "创建模型服务失败"));
    } finally {
      setSaving(false);
    }
  }

  function replaceProvider(updated: ProviderResource) {
    setProviders((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    onProvidersChanged?.();
  }

  function removeProvider(providerId: string) {
    setProviders((prev) => prev.filter((p) => p.id !== providerId));
    onProvidersChanged?.();
  }

  function closeCreateForm() {
    const dirty = Boolean(name.trim() || baseUrl.trim() || apiKey.trim());
    if (dirty && !globalThis.confirm("放弃未保存的模型服务配置？")) return;
    setName("");
    setBaseUrl("");
    setApiKey("");
    setCreateExpanded(false);
  }

  return (
    <Card title="模型服务" icon={<Server size={18} aria-hidden="true" />}>
      <p className="settings-section-intro">模型服务和密钥由所有工作区复用；一次只展开一个服务进行管理。</p>
      <div className="btn-row"><Button variant={createExpanded ? "secondary" : "primary"} aria-expanded={createExpanded} aria-controls="provider-create-form" onClick={() => setCreateExpanded((expanded) => !expanded)}><Plus size={16} aria-hidden="true" />添加模型服务</Button></div>
      {createExpanded ? <div id="provider-create-form" className="settings-disclosure-panel"><div className="field-group provider-form-grid">
        <Field label="服务名称" name="new-provider-name" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="field">
          <label className="field__label" htmlFor="new-provider-format">
            协议
          </label>
          <SelectControl
            id="new-provider-format"
            name="new-provider-format"
            className="field__input"
            value={apiFormat}
            onChange={(e) => setApiFormat(e.target.value as ProviderFormat)}
          >
            <option value="openai-compatible">OpenAI 兼容</option>
            <option value="anthropic-compatible">Anthropic 兼容</option>
          </SelectControl>
        </div>
        <Field
          label="Base URL"
          name="new-provider-base-url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
        />
        <Field
          label="API Key"
          name="new-provider-api-key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          helper="仅写入，不会回显、缓存或保存到本地"
          autoComplete="off"
        />
      </div>
      <div className="btn-row">
        <Button onClick={handleCreate} loading={saving} disabled={saving}>
          保存模型服务
        </Button>
        <Button variant="ghost" onClick={closeCreateForm} disabled={saving}>取消添加</Button>
      </div>
      </div> : null}

      {loading ? <p className="status-note">加载中…</p> : null}
      {!loading && providers.length === 0 ? <p className="status-note">还没有模型服务</p> : null}

      {providers.map((provider) => (
        <ProviderCard
          key={provider.id}
          provider={provider}
          expanded={expandedProviderId === provider.id}
          onToggle={() => setExpandedProviderId((current) => current === provider.id ? null : provider.id)}
          onUpdated={replaceProvider}
          onRemoved={removeProvider}
        />
      ))}

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

interface ProviderCardProps {
  provider: ProviderResource;
  expanded: boolean;
  onToggle: () => void;
  onUpdated: (provider: ProviderResource) => void;
  onRemoved: (providerId: string) => void;
}

function ProviderCard({ provider, expanded, onToggle, onUpdated, onRemoved }: ProviderCardProps) {
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(provider.name);
  const [editFormat, setEditFormat] = useState<ProviderFormat>(provider.apiFormat);
  const [editBaseUrl, setEditBaseUrl] = useState(provider.baseUrl);
  const [editApiKey, setEditApiKey] = useState("");
  const [savingProvider, setSavingProvider] = useState(false);
  const [deletingProvider, setDeletingProvider] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);

  const [modelId, setModelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [maxInputTokens, setMaxInputTokens] = useState("128000");
  const [addingModel, setAddingModel] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [editModelId, setEditModelId] = useState("");
  const [editModelDisplay, setEditModelDisplay] = useState("");
  const [editModelMaxInputTokens, setEditModelMaxInputTokens] = useState("");

  function updateModels(updater: (models: ProviderModelResource[]) => ProviderModelResource[]) {
    onUpdated({ ...provider, models: updater(provider.models) });
  }

  async function handleSaveProvider() {
    setError(null);
    setConflict(null);
    setSavingProvider(true);
    try {
      const command: UpdateProviderCommand = {
        name: editName.trim(),
        apiFormat: editFormat,
        baseUrl: editBaseUrl.trim(),
      };
      if (editApiKey.trim()) {
        command.apiKey = editApiKey.trim();
      }
      const updated = await updateProvider(provider.id, command);
      onUpdated(updated);
      setEditApiKey("");
      setEditing(false);
    } catch (caught) {
      setError(toActionableError(caught, "保存模型服务失败"));
    } finally {
      setSavingProvider(false);
    }
  }

  async function handleDeleteProvider() {
    setError(null);
    setConflict(null);
    setDeletingProvider(true);
    try {
      await deleteProvider(provider.id);
      onRemoved(provider.id);
    } catch (caught) {
      if (isResourceInUse(caught)) {
        setConflict(caught.message);
      } else {
        setError(toActionableError(caught, "删除模型服务失败"));
      }
    } finally {
      setDeletingProvider(false);
    }
  }

  async function handleAddModel() {
    setError(null);
    const contextWindow = Number(maxInputTokens);
    if (!modelId.trim() || !displayName.trim() || !Number.isInteger(contextWindow) || contextWindow < 4096) {
      setError(toActionableError(new Error("请填写模型信息，并将最大输入 Token 设为不小于 4096 的整数"), "添加模型失败"));
      return;
    }
    setAddingModel(true);
    try {
      const created = await createProviderModel(provider.id, {
        modelId: modelId.trim(),
        displayName: displayName.trim(),
        maxInputTokens: contextWindow,
      });
      updateModels((models) => [...models, created]);
      setModelId("");
      setDisplayName("");
      setMaxInputTokens("128000");
    } catch (caught) {
      setError(toActionableError(caught, "添加模型失败"));
    } finally {
      setAddingModel(false);
    }
  }

  async function handleTestModel(model: ProviderModelResource) {
    setError(null);
    setTestingId(model.id);
    try {
      const updated = await testProviderModel(model.id);
      updateModels((models) => models.map((m) => (m.id === updated.id ? updated : m)));
    } catch (caught) {
      setError(toActionableError(caught, "测试模型失败"));
    } finally {
      setTestingId(null);
    }
  }

  async function handleDeleteModel(model: ProviderModelResource) {
    setError(null);
    setConflict(null);
    try {
      await deleteProviderModel(model.id);
      updateModels((models) => models.filter((m) => m.id !== model.id));
    } catch (caught) {
      if (isResourceInUse(caught)) {
        setConflict(caught.message);
      } else {
        setError(toActionableError(caught, "删除模型失败"));
      }
    }
  }

  function startEditModel(model: ProviderModelResource) {
    setEditingModelId(model.id);
    setEditModelId(model.modelId);
    setEditModelDisplay(model.displayName);
    setEditModelMaxInputTokens(String(model.maxInputTokens));
  }

  async function handleSaveModel(model: ProviderModelResource) {
    setError(null);
    const contextWindow = Number(editModelMaxInputTokens);
    if (!editModelId.trim() || !editModelDisplay.trim() || !Number.isInteger(contextWindow) || contextWindow < 4096) {
      setError(toActionableError(new Error("请填写模型信息，并将最大输入 Token 设为不小于 4096 的整数"), "保存模型失败"));
      return;
    }
    try {
      const command: UpdateProviderModelCommand = {
        modelId: editModelId.trim(),
        displayName: editModelDisplay.trim(),
        maxInputTokens: contextWindow,
      };
      const updated = await updateProviderModel(model.id, command);
      updateModels((models) => models.map((m) => (m.id === updated.id ? updated : m)));
      setEditingModelId(null);
    } catch (caught) {
      setError(toActionableError(caught, "保存模型失败"));
    }
  }

  return (
    <div className="provider-card" data-expanded={expanded} aria-label={`模型服务 ${provider.name}`}>
      <div className="provider-card__header">
        <div className="provider-card__title">
          <h4 className="provider-card__name">{provider.name}</h4>
          <Badge tone={provider.hasSecret ? "success" : "warning"} dot>
            {provider.hasSecret ? "密钥已配置" : "缺少密钥"}
          </Badge>
          <span className="muted-text">{provider.models.length} 个模型</span>
        </div>
        <div className="btn-row">
          <Button
            variant="secondary"
            size="sm"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={`管理模型服务 ${provider.name}`}
          >
            管理
            <ChevronDown className="provider-card__chevron" size={15} aria-hidden="true" />
          </Button>
        </div>
      </div>

      {expanded ? <div className="provider-card__details">
      <div className="provider-card__overview">
        <div>
          <span>连接协议</span>
          <strong>{FORMAT_LABEL[provider.apiFormat]}</strong>
        </div>
        <div>
          <span>服务地址</span>
          <strong title={provider.baseUrl}>{provider.baseUrl}</strong>
        </div>
        <div>
          <span>服务状态</span>
          <strong>{provider.enabled ? "已启用" : "已停用"}</strong>
        </div>
      </div>
      <div className="btn-row">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setEditing((prev) => !prev);
            setEditApiKey("");
          }}
          aria-label={`编辑模型服务 ${provider.name}`}
        >
          <Pencil size={14} aria-hidden="true" />
          编辑服务
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={handleDeleteProvider}
          loading={deletingProvider}
          aria-label={`删除模型服务 ${provider.name}`}
        >
          <Trash2 size={14} aria-hidden="true" />
          删除服务
        </Button>
      </div>
      {editing ? (
        <div className="field-group provider-card__edit">
          <Field label="服务名称" name={`edit-name-${provider.id}`} value={editName} onChange={(e) => setEditName(e.target.value)} />
          <div className="field">
            <label className="field__label" htmlFor={`edit-format-${provider.id}`}>协议</label>
            <SelectControl
              id={`edit-format-${provider.id}`}
              name={`edit-format-${provider.id}`}
              className="field__input"
              value={editFormat}
              onChange={(e) => setEditFormat(e.target.value as ProviderFormat)}
            >
              <option value="openai-compatible">OpenAI 兼容</option>
              <option value="anthropic-compatible">Anthropic 兼容</option>
            </SelectControl>
          </div>
          <Field label="Base URL" name={`edit-base-url-${provider.id}`} value={editBaseUrl} onChange={(e) => setEditBaseUrl(e.target.value)} />
          <Field
            label="API Key（留空保留原密钥）"
            name={`edit-api-key-${provider.id}`}
            type="password"
            value={editApiKey}
            onChange={(e) => setEditApiKey(e.target.value)}
            helper="仅写入，不会回显"
            autoComplete="off"
          />
          <div className="btn-row">
            <Button size="sm" onClick={handleSaveProvider} loading={savingProvider}>保存</Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setEditApiKey(""); }}>
              <X size={14} aria-hidden="true" />
              取消
            </Button>
          </div>
        </div>
      ) : null}

      <div className="provider-card__models">
        <p className="muted-text">模型</p>
        {provider.models.length === 0 ? <p className="status-note">暂无模型</p> : null}
        {provider.models.map((model) => (
          <div className="model-row" key={model.id}>
            {editingModelId === model.id ? (
              <div className="field-group">
                <Field label="Model ID" name={`edit-model-id-${model.id}`} value={editModelId} onChange={(e) => setEditModelId(e.target.value)} />
                <Field label="显示名称" name={`edit-model-display-${model.id}`} value={editModelDisplay} onChange={(e) => setEditModelDisplay(e.target.value)} />
                <Field label="最大输入 Token" name={`edit-model-context-${model.id}`} type="number" min={4096} max={2000000} step={1024} value={editModelMaxInputTokens} onChange={(e) => setEditModelMaxInputTokens(e.target.value)} />
                <div className="btn-row">
                  <Button size="sm" onClick={() => handleSaveModel(model)}>保存</Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingModelId(null)}>取消</Button>
                </div>
              </div>
            ) : (
              <div className="model-row__main">
                <strong className="model-row__name">{model.displayName}</strong>
                <span className="model-row__id" title="模型技术 ID">{model.modelId}</span>
                <span className="model-row__context">{(model.maxInputTokens / 1000).toFixed(model.maxInputTokens >= 100000 ? 0 : 1)}k 上下文</span>
                <Badge tone={STATUS_TONE[model.connectivityStatus]} dot>
                  {STATUS_LABEL[model.connectivityStatus]}
                </Badge>
                <div className="btn-row">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleTestModel(model)}
                    loading={testingId === model.id}
                    aria-label={`测试模型 ${model.modelId}`}
                  >
                    <FlaskConical size={14} aria-hidden="true" />
                    测试
                  </Button>
                  <Button size="sm" variant="ghost" aria-label={`编辑模型 ${model.modelId}`} onClick={() => startEditModel(model)}>
                    <Pencil size={14} aria-hidden="true" />
                    编辑
                  </Button>
                  <Button size="sm" variant="danger" aria-label={`删除模型 ${model.modelId}`} onClick={() => handleDeleteModel(model)}>
                    <Trash2 size={14} aria-hidden="true" />
                    删除
                  </Button>
                </div>
              </div>
            )}
          </div>
        ))}

        <div className="field-group model-row__add">
          <Field label="Model ID" name={`new-model-id-${provider.id}`} value={modelId} onChange={(e) => setModelId(e.target.value)} />
          <Field label="显示名称" name={`new-model-display-${provider.id}`} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <Field label="最大输入 Token" name={`new-model-context-${provider.id}`} type="number" min={4096} max={2000000} step={1024} value={maxInputTokens} onChange={(e) => setMaxInputTokens(e.target.value)} helper="用于计算 70% 上下文压缩阈值" />
          <Button size="sm" onClick={handleAddModel} loading={addingModel}>
            <Plus size={14} aria-hidden="true" />
            添加模型
          </Button>
        </div>
      </div>

      {conflict ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>{conflict}</span>
          <span>{UNBIND_ADVICE}</span>
        </div>
      ) : null}
      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>错误：{error.message}</span>
          <span>{error.advice}</span>
        </div>
      ) : null}
      </div> : null}
    </div>
  );
}
