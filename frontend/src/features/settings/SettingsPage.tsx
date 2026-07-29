import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Server } from "lucide-react";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
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
  type WorkspaceConfig,
} from "./settingsApi";
import { SettingsNavigation, type SettingsSection } from "./SettingsNavigation";
import { SettingsOverview, type SettingsStatusItem } from "./SettingsOverview";
import { SettingsDisclosure } from "./SettingsDisclosure";
import { WorkspaceManager } from "./WorkspaceManager";
import { AgentDiagnosticsSettings } from "./AgentDiagnosticsSettings";
import { AgentTraceRetentionSettings } from "./AgentTraceRetentionSettings";

const REQUIRED_MODEL_ROLE_COUNT = 8;

interface SettingsPageProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceReady: (workspace: WorkspaceConfig | null) => void;
}

export function SettingsPage({ workspace, onWorkspaceReady }: SettingsPageProps) {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);
  const [providerRevision, setProviderRevision] = useState(0);
  const [section, setSection] = useState<SettingsSection>("overview");
  const [modelBindingsDirty, setModelBindingsDirty] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    const requested = new URLSearchParams(globalThis.location.search).get("section");
    if (requested === "workspace" || requested === "models" || requested === "diagnostics") {
      setSection(requested);
    }
  }, []);

  useEffect(() => {
    if (!workspace) {
      setWorkspaceId(null);
      return;
    }
    let cancelled = false;
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
          setWorkspaceId(null);
          setError(toActionableError(new Error("当前工作区未注册"), "恢复工作区失败"));
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
        status: workspace ? "已就绪" : "未创建",
        description: workspace?.workspacePath ?? "需要先创建或关联一个本地工作区",
        tone: workspace ? "success" : "warning",
        section: "workspace",
      },
      {
        id: "providers",
        title: "模型服务",
        status: providersQuery.isError ? "读取失败" : providersQuery.isLoading ? "加载中…" : `${providersQuery.data?.length ?? 0} 个已配置`,
        description: providersQuery.isError ? "进入模型服务查看错误和恢复建议" : providersQuery.data?.length ? "模型服务已准备好继续分配任务" : "尚未添加模型服务",
        tone: providersQuery.isError ? "danger" : providersQuery.data?.length ? "success" : "warning",
        section: "models",
      },
      {
        id: "bindings",
        title: "任务模型",
        status: bindingsQuery.isError ? "读取失败" : `${bindingCount}/${REQUIRED_MODEL_ROLE_COUNT} 已绑定`,
        description: bindingsQuery.isError ? "进入模型服务查看分配状态" : bindingCount === REQUIRED_MODEL_ROLE_COUNT ? "所有任务均已分配模型" : "补齐任务模型后即可使用相关助手功能",
        tone: bindingsQuery.isError ? "danger" : bindingCount === REQUIRED_MODEL_ROLE_COUNT ? "success" : "warning",
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
      : Object.values(bindingsQuery.data?.bindings ?? {}).filter(Boolean).length < REQUIRED_MODEL_ROLE_COUNT
        ? "models"
        : "diagnostics";

  function selectSection(next: SettingsSection) {
    if (
      section === "models" &&
      next !== "models" &&
      modelBindingsDirty &&
      !globalThis.confirm("模型配置还没有保存，确定离开吗？")
    ) {
      return;
    }
    setSection(next);
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
        {workspace ? <span className="page-section__hint">管理工作区与模型服务</span> : null}
      </div>

      <div className="settings-layout">
        <SettingsNavigation
          current={section}
          onSelect={selectSection}
          disabledSections={workspaceId ? [] : ["models", "diagnostics"]}
        />
        <div className="settings-content">
          {section === "overview" ? (
            <SettingsOverview
              items={overviewItems}
              recommendedSection={recommendedSection}
              onSelect={(next) => {
                selectSection(next);
              }}
            />
          ) : null}

          {section === "workspace" ? (
            <WorkspaceManager
              workspace={workspace}
              onWorkspaceChanged={onWorkspaceReady}
            />
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
                onDirtyChange={setModelBindingsDirty}
              />
            </div>
          ) : null}

          {section === "diagnostics" && workspaceId ? (
            <div className="settings-stack">
              <SettingsDisclosure
                id="agent-diagnostics"
                title="Agent 运行与诊断"
                description="控制本机高级 Trace 正文查看"
                defaultExpanded
              >
                <AgentDiagnosticsSettings />
                <AgentTraceRetentionSettings workspaceId={workspaceId} />
              </SettingsDisclosure>
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
