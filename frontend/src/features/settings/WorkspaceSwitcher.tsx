import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, FolderCog, LoaderCircle, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { WorkspaceResource } from "./providerTypes";
import {
  listWorkspaces,
  selectWorkspace,
  type WorkspaceConfig,
} from "./settingsApi";

interface WorkspaceSwitcherProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceSelected: (workspace: WorkspaceConfig) => void;
}

function toConfig(workspace: WorkspaceResource): WorkspaceConfig {
  return {
    id: workspace.id,
    displayName: workspace.displayName,
    workspacePath: workspace.rootPath,
    vaultPath: workspace.vaultPath,
  };
}

export function WorkspaceSwitcher({
  workspace,
  onWorkspaceSelected,
}: WorkspaceSwitcherProps) {
  const [workspaces, setWorkspaces] = useState<WorkspaceResource[]>([]);
  const [loading, setLoading] = useState(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void listWorkspaces()
      .then((items) => {
        if (!cancelled) {
          setWorkspaces(items);
          setError("");
        }
      })
      .catch(() => {
        if (!cancelled) setError("无法读取工作区");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspace?.id]);

  async function handleSelect(candidate: WorkspaceResource) {
    if (
      document.body.dataset.modelBindingsDirty === "true" &&
      !globalThis.confirm("模型配置还没有保存，确定切换工作区吗？")
    ) {
      return;
    }
    if (candidate.id === workspace?.id) {
      detailsRef.current?.removeAttribute("open");
      return;
    }
    setSwitchingId(candidate.id);
    setError("");
    try {
      const selected = await selectWorkspace(candidate.id);
      setWorkspaces((current) =>
        current.map((item) => ({
          ...item,
          isCurrent: item.id === selected.id,
        })),
      );
      onWorkspaceSelected(toConfig(selected));
      detailsRef.current?.removeAttribute("open");
    } catch {
      setError("切换失败，请到设置中检查路径");
    } finally {
      setSwitchingId(null);
    }
  }

  function openManager() {
    detailsRef.current?.removeAttribute("open");
    navigate("/settings?section=workspace");
  }

  const currentName =
    workspace?.displayName ||
    workspace?.workspacePath.split(/[\\/]/).filter(Boolean).at(-1) ||
    "尚未创建工作区";

  return (
    <details className="workspace-switcher" ref={detailsRef}>
      <summary className="workspace-switcher__trigger">
        <span className="workspace-switcher__icon" aria-hidden="true">
          <FolderCog size={17} />
        </span>
        <span className="workspace-switcher__current">
          <span className="workspace-switcher__label">当前工作区</span>
          <strong title={workspace?.workspacePath}>{currentName}</strong>
        </span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>

      <div className="workspace-switcher__menu">
        <p className="workspace-switcher__menu-title">切换工作区</p>
        {loading ? (
          <p className="workspace-switcher__state">
            <LoaderCircle className="workspace-switcher__spinner" size={15} />
            正在读取…
          </p>
        ) : null}
        {!loading && workspaces.length === 0 ? (
          <p className="workspace-switcher__state">还没有可用工作区</p>
        ) : null}
        {workspaces.map((candidate) => {
          const selected = candidate.id === workspace?.id;
          return (
            <button
              className="workspace-switcher__option"
              type="button"
              key={candidate.id}
              disabled={!candidate.available || switchingId !== null}
              onClick={() => void handleSelect(candidate)}
            >
              <span className="workspace-switcher__option-copy">
                <strong>{candidate.displayName}</strong>
                <span>
                  {candidate.activeExecutionCount > 0
                    ? `${candidate.activeExecutionCount} 个任务运行中`
                    : candidate.available
                      ? "可以切换"
                      : "路径不可用"}
                </span>
              </span>
              {switchingId === candidate.id ? (
                <LoaderCircle className="workspace-switcher__spinner" size={16} />
              ) : selected ? (
                <Check size={16} aria-label="当前工作区" />
              ) : null}
            </button>
          );
        })}
        {error ? <p className="workspace-switcher__error" role="alert">{error}</p> : null}
        <button className="workspace-switcher__manage" type="button" onClick={openManager}>
          <Plus size={16} aria-hidden="true" />
          新建或管理工作区
        </button>
      </div>
    </details>
  );
}
