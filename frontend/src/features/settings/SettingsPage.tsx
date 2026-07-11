import { useEffect, useState } from "react";
import { AlertCircle, FolderCog, Server } from "lucide-react";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { Field } from "../../shared/ui/Field";
import { ModelBindings } from "./ModelBindings";
import { ProviderManager } from "./ProviderManager";
import { RuntimeDiagnostics } from "./RuntimeDiagnostics";
import { SecurityDiagnostics } from "./SecurityDiagnostics";
import { ActionCenter } from "../agent/ActionCenter";
import {
  listWorkspaces,
  registerWorkspace,
  type WorkspaceConfig,
} from "./settingsApi";

interface SettingsPageProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceReady: (workspace: WorkspaceConfig) => void;
}

export function SettingsPage({ workspace, onWorkspaceReady }: SettingsPageProps) {
  const [workspacePath, setWorkspacePath] = useState(workspace?.workspacePath ?? "");
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [workspaceMessage, setWorkspaceMessage] = useState("");
  const [error, setError] = useState<ActionableError | null>(null);
  const [isInitializingWorkspace, setIsInitializingWorkspace] = useState(false);
  const [providerRevision, setProviderRevision] = useState(0);

  useEffect(() => {
    if (!workspace) {
      setWorkspaceId(null);
      return;
    }
    let cancelled = false;
    setWorkspacePath(workspace.workspacePath);
    void listWorkspaces()
      .then((workspaces) => {
        if (cancelled) return;
        const registered = workspaces.find(
          (candidate) => candidate.rootPath === workspace.workspacePath,
        );
        if (registered) {
          setWorkspaceId(registered.id);
          setError(null);
        } else {
          return registerWorkspace(workspace.workspacePath).then((created) => {
            if (!cancelled) setWorkspaceId(created.id);
          });
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(toActionableError(caught, "恢复工作区失败"));
      });
    return () => {
      cancelled = true;
    };
  }, [workspace]);

  async function handleWorkspaceInit() {
    setError(null);
    setWorkspaceMessage("");
    const trimmedPath = workspacePath.trim();
    if (!trimmedPath) {
      setError(toActionableError(new Error("请输入 Workspace Path"), "初始化工作区失败"));
      return;
    }
    setIsInitializingWorkspace(true);
    try {
      const registered = await registerWorkspace(trimmedPath);
      const ready = {
        id: registered.id,
        workspacePath: registered.rootPath,
        vaultPath: registered.vaultPath,
      };
      setWorkspaceId(registered.id);
      onWorkspaceReady(ready);
      setWorkspaceMessage(`Vault：${registered.vaultPath}`);
    } catch (caught) {
      setError(toActionableError(caught, "初始化工作区失败"));
    } finally {
      setIsInitializingWorkspace(false);
    }
  }

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
          {workspace ? (
            <Badge tone="success" dot>
              {workspace.workspacePath}
            </Badge>
          ) : null}
        </div>
        {workspaceMessage ? <p className="status-note">{workspaceMessage}</p> : null}
      </Card>

      {workspaceId ? (
        <div className="settings-stack">
          <ProviderManager
            onProvidersChanged={() => setProviderRevision((revision) => revision + 1)}
          />
          <ModelBindings workspaceId={workspaceId} refreshKey={providerRevision} />
          <RuntimeDiagnostics workspaceId={workspaceId} />
          <SecurityDiagnostics workspaceId={workspaceId} />
          <ActionCenter workspaceId={workspaceId} />
        </div>
      ) : workspace ? (
        <p className="status-note">正在恢复 Workspace 配置…</p>
      ) : null}

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
