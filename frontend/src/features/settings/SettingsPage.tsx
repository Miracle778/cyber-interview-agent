import { useState } from "react";
import { AlertCircle, FolderCog, Server } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { Badge } from "../../shared/ui/Badge";
import { Field } from "../../shared/ui/Field";
import { initializeWorkspace, testProviderConnection, type ProviderConfig, type WorkspaceConfig } from "./settingsApi";

interface SettingsPageProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceReady: (workspace: WorkspaceConfig) => void;
}

export function SettingsPage({ workspace, onWorkspaceReady }: SettingsPageProps) {
  const [providerName, setProviderName] = useState("OpenAI Compatible");
  const [baseUrl, setBaseUrl] = useState("https://api.example.com/v1");
  const [modelId, setModelId] = useState("model-a");
  const [workspacePath, setWorkspacePath] = useState("");
  const [providerStatus, setProviderStatus] = useState<ProviderConfig["connectivityStatus"] | null>(null);
  const [workspaceMessage, setWorkspaceMessage] = useState("");
  const [error, setError] = useState("");
  const [isTestingProvider, setIsTestingProvider] = useState(false);
  const [isInitializingWorkspace, setIsInitializingWorkspace] = useState(false);

  async function handleProviderTest() {
    setError("");
    setProviderStatus(null);
    setIsTestingProvider(true);
    try {
      const provider = await testProviderConnection({
        id: "local-provider",
        name: providerName,
        apiFormat: "openai-compatible",
        baseUrl,
        modelIds: [modelId],
        activeModelId: modelId,
        connectivityStatus: "unknown",
      });
      setProviderStatus(provider.connectivityStatus);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider 测试失败");
    } finally {
      setIsTestingProvider(false);
    }
  }

  async function handleWorkspaceInit() {
    setError("");
    setWorkspaceMessage("");
    const trimmedPath = workspacePath.trim();
    if (!trimmedPath) {
      setError("请输入 Workspace Path");
      return;
    }
    setIsInitializingWorkspace(true);
    try {
      const initializedWorkspace = await initializeWorkspace(trimmedPath);
      onWorkspaceReady(initializedWorkspace);
      setWorkspaceMessage(`Vault：${initializedWorkspace.vaultPath}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "初始化工作区失败");
    } finally {
      setIsInitializingWorkspace(false);
    }
  }

  const statusTone = providerStatus === "ok" ? "success" : providerStatus ? "danger" : "neutral";

  return (
    <section className="page-section" aria-labelledby="settings-title">
      <div className="page-section__header">
        <span className="page-section__icon" aria-hidden="true">
          <Server size={18} />
        </span>
        <h2 id="settings-title" className="page-section__title">
          设置
        </h2>
        {workspace ? <span className="page-section__hint">配置 Provider 与工作区</span> : null}
      </div>

      <Card title="Provider 配置" icon={<Server size={18} />}>
        <div className="field-group">
          <Field label="Provider 名称" name="providerName" value={providerName} onChange={(event) => setProviderName(event.target.value)} />
          <Field label="Base URL" name="baseUrl" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          <Field label="Model ID" name="modelId" value={modelId} onChange={(event) => setModelId(event.target.value)} />
        </div>
        <div className="btn-row">
          <Button onClick={handleProviderTest} loading={isTestingProvider}>
            测试连接
          </Button>
          {providerStatus ? (
            <Badge tone={statusTone} dot>
              {providerStatus === "ok" ? "已连接" : "连接异常"}
            </Badge>
          ) : null}
        </div>
        {providerStatus ? (
          <p className="status-note" data-status={providerStatus}>
            Provider 连接状态：{providerStatus}
          </p>
        ) : null}
      </Card>

      <Card title="工作区" icon={<FolderCog size={18} />}>
        <Field
          label="Workspace Path"
          name="workspacePath"
          value={workspacePath}
          onChange={(event) => setWorkspacePath(event.target.value)}
          helper="初始化会创建 Obsidian 兼容的 knowledge-vault 目录结构"
        />
        <div className="btn-row">
          <Button onClick={handleWorkspaceInit} loading={isInitializingWorkspace}>
            初始化工作区
          </Button>
          {workspace ? <Badge tone="success" dot>{workspace.workspacePath}</Badge> : null}
        </div>
        {workspaceMessage ? <p className="status-note">{workspaceMessage}</p> : null}
      </Card>

      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}
    </section>
  );
}
