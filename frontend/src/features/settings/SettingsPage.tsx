import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { listActions } from "../agent/hitlApi";
import {
  listWorkspaces,
  listProviders,
  getWorkspaceModelBindings,
  registerWorkspace,
  type WorkspaceConfig,
} from "./settingsApi";
import { SettingsNavigation, type SettingsSection } from "./SettingsNavigation";
import { SettingsOverview, type SettingsStatusItem } from "./SettingsOverview";
import { SettingsDisclosure } from "./SettingsDisclosure";

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
  const [section, setSection] = useState<SettingsSection>("overview");
  const queryClient = useQueryClient();

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

  const providersQuery = useQuery({
    queryKey: ["settings-providers-summary"],
    queryFn: listProviders,
    enabled: Boolean(workspaceId),
  });
  const bindingsQuery = useQuery({
    queryKey: ["workspace-model-bindings", workspaceId],
    queryFn: () => getWorkspaceModelBindings(workspaceId!),
    enabled: Boolean(workspaceId),
  });
  const actionsQuery = useQuery({
    queryKey: ["pending-actions", workspaceId],
    queryFn: () => listActions(workspaceId!, { status: "pending" }),
    enabled: Boolean(workspaceId),
  });

  const overviewItems = useMemo<SettingsStatusItem[]>(() => {
    const bindingCount = Object.values(bindingsQuery.data?.bindings ?? {}).filter(Boolean).length;
    const pendingCount = actionsQuery.data?.length ?? 0;
    return [
      {
        id: "workspace",
        title: "工作区",
        status: workspace ? "已就绪" : "未初始化",
        description: workspace?.workspacePath ?? "需要先初始化 Workspace",
        tone: workspace ? "success" : "warning",
        section: "workspace",
      },
      {
        id: "providers",
        title: "Provider",
        status: providersQuery.isError ? "读取失败" : providersQuery.isLoading ? "加载中…" : `${providersQuery.data?.length ?? 0} 个已配置`,
        description: providersQuery.isError ? "进入模型服务查看错误和恢复建议" : providersQuery.data?.length ? "模型服务已准备好继续绑定用途" : "尚未添加 Provider",
        tone: providersQuery.isError ? "danger" : providersQuery.data?.length ? "success" : "warning",
        section: "models",
      },
      {
        id: "bindings",
        title: "模型用途绑定",
        status: bindingsQuery.isError ? "读取失败" : `${bindingCount}/4 已绑定`,
        description: bindingsQuery.isError ? "进入模型服务查看绑定状态" : bindingCount === 4 ? "四种用途均已有模型" : "完成四种用途绑定后才能运行复习",
        tone: bindingsQuery.isError ? "danger" : bindingCount === 4 ? "success" : "warning",
        section: "models",
      },
      {
        id: "diagnostics",
        title: "运行诊断",
        status: pendingCount > 0 ? `${pendingCount} 个待确认动作` : "待检查",
        description: pendingCount > 0 ? "有动作需要人工决定" : "Runtime、自检和安全检查按需运行",
        tone: pendingCount > 0 ? "danger" : "neutral",
        section: "diagnostics",
      },
    ];
  }, [actionsQuery.data, bindingsQuery.data, bindingsQuery.isError, providersQuery.data, providersQuery.isError, providersQuery.isLoading, workspace]);

  const recommendedSection: Exclude<SettingsSection, "overview"> = !workspaceId
    ? "workspace"
    : (providersQuery.data?.length ?? 0) === 0
      ? "models"
      : Object.values(bindingsQuery.data?.bindings ?? {}).filter(Boolean).length < 4
        ? "models"
        : "diagnostics";

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

      <div className="settings-layout">
        <SettingsNavigation
          current={section}
          onSelect={setSection}
          disabledSections={workspaceId ? [] : ["models", "diagnostics"]}
        />
        <div className="settings-content">
          {section === "overview" ? (
            <SettingsOverview
              items={overviewItems}
              recommendedSection={recommendedSection}
              onSelect={(next) => {
                if (next === "workspace" && !workspace) setSection("workspace");
                else setSection(next);
              }}
            />
          ) : null}

          {section === "workspace" ? (
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
          ) : null}

          {section === "models" && workspaceId ? (
            <div className="settings-stack">
              <ProviderManager
                onProvidersChanged={() => {
                  setProviderRevision((revision) => revision + 1);
                  void queryClient.invalidateQueries({ queryKey: ["settings-providers-summary"] });
                  void queryClient.invalidateQueries({ queryKey: ["workspace-model-bindings", workspaceId] });
                }}
              />
              <ModelBindings
                workspaceId={workspaceId}
                refreshKey={providerRevision}
                onBindingsChanged={() => void queryClient.invalidateQueries({ queryKey: ["workspace-model-bindings", workspaceId] })}
              />
            </div>
          ) : null}

          {section === "diagnostics" && workspaceId ? (
            <div className="settings-stack">
              <SettingsDisclosure id="runtime" title="Agent Runtime" description="运行 Runtime 自检并查看事件流">
                <RuntimeDiagnostics workspaceId={workspaceId} />
              </SettingsDisclosure>
              <SettingsDisclosure id="security" title="工具安全" description="检查工具白名单、Scope 与路径边界">
                <SecurityDiagnostics workspaceId={workspaceId} />
              </SettingsDisclosure>
              <SettingsDisclosure id="approval" title="人工确认" description={actionsQuery.data?.length ? `${actionsQuery.data.length} 个动作等待决定` : "没有待处理动作"} defaultExpanded={Boolean(actionsQuery.data?.length)}>
                <ActionCenter workspaceId={workspaceId} />
              </SettingsDisclosure>
            </div>
          ) : null}
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
