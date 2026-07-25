import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArchiveRestore,
  Check,
  FolderPlus,
  Pencil,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Field } from "../../shared/ui/Field";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import type {
  WorkspaceDeletionImpactResource,
  WorkspaceResource,
} from "./providerTypes";
import {
  getWorkspaceDeletionImpact,
  listWorkspaces,
  permanentlyDeleteWorkspace,
  recycleWorkspace,
  registerWorkspace,
  restoreWorkspace,
  selectWorkspace,
  updateWorkspace,
  type WorkspaceConfig,
} from "./settingsApi";

interface WorkspaceManagerProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceChanged: (workspace: WorkspaceConfig | null) => void;
}

function toConfig(resource: WorkspaceResource): WorkspaceConfig {
  return {
    id: resource.id,
    displayName: resource.displayName,
    workspacePath: resource.rootPath,
    vaultPath: resource.vaultPath,
  };
}

export function WorkspaceManager({
  workspace,
  onWorkspaceChanged,
}: WorkspaceManagerProps) {
  const [items, setItems] = useState<WorkspaceResource[]>([]);
  const [rootPath, setRootPath] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [recycleConfirmId, setRecycleConfirmId] = useState<string | null>(null);
  const [deleteImpact, setDeleteImpact] =
    useState<WorkspaceDeletionImpactResource | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [error, setError] = useState<ActionableError | null>(null);

  const activeItems = useMemo(
    () => items.filter((item) => item.lifecycleStatus === "active"),
    [items],
  );
  const recycledItems = useMemo(
    () => items.filter((item) => item.lifecycleStatus === "recycled"),
    [items],
  );

  useEffect(() => {
    void refresh();
  }, [workspace?.id]);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await listWorkspaces("all"));
      setError(null);
    } catch (caught) {
      setError(toActionableError(caught, "读取工作区失败"));
    } finally {
      setLoading(false);
    }
  }

  async function createWorkspace() {
    setError(null);
    if (!rootPath.trim()) {
      setError(toActionableError(new Error("请输入本地文件夹路径"), "创建工作区失败"));
      return;
    }
    setBusyId("create");
    try {
      const created = await registerWorkspace(
        rootPath.trim(),
        displayName.trim() || undefined,
      );
      onWorkspaceChanged(toConfig(created));
      setRootPath("");
      setDisplayName("");
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "创建工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function chooseWorkspace(resource: WorkspaceResource) {
    setBusyId(resource.id);
    setError(null);
    try {
      const selected = await selectWorkspace(resource.id);
      onWorkspaceChanged(toConfig(selected));
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "切换工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function saveName(resource: WorkspaceResource) {
    setBusyId(resource.id);
    setError(null);
    try {
      const updated = await updateWorkspace(resource.id, {
        displayName: editingName,
      });
      if (updated.id === workspace?.id) onWorkspaceChanged(toConfig(updated));
      setEditingId(null);
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "重命名工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function recycle(resource: WorkspaceResource) {
    setBusyId(resource.id);
    setError(null);
    try {
      await recycleWorkspace(resource.id);
      if (resource.id === workspace?.id) onWorkspaceChanged(null);
      setRecycleConfirmId(null);
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "删除工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function restore(resource: WorkspaceResource) {
    setBusyId(resource.id);
    setError(null);
    try {
      const restored = await restoreWorkspace(resource.id);
      if (restored.isCurrent) onWorkspaceChanged(toConfig(restored));
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "恢复工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function preparePermanentDelete(resource: WorkspaceResource) {
    setBusyId(resource.id);
    setError(null);
    try {
      setDeleteImpact(await getWorkspaceDeletionImpact(resource.id));
      setDeleteConfirmation("");
    } catch (caught) {
      setError(toActionableError(caught, "读取删除影响失败"));
    } finally {
      setBusyId(null);
    }
  }

  async function deletePermanently() {
    if (!deleteImpact) return;
    setBusyId(deleteImpact.workspaceId);
    setError(null);
    try {
      await permanentlyDeleteWorkspace(
        deleteImpact.workspaceId,
        deleteConfirmation,
      );
      setDeleteImpact(null);
      setDeleteConfirmation("");
      await refresh();
    } catch (caught) {
      setError(toActionableError(caught, "永久删除工作区失败"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="workspace-manager" aria-labelledby="workspace-manager-title">
      <div className="settings-content__header">
        <div>
          <p className="settings-content__eyebrow">数据空间</p>
          <h3 id="workspace-manager-title">工作区管理</h3>
          <p className="settings-content__description">
            不同工作区的资料、会话和题库相互隔离。删除不会动你的本机 Vault 文件夹。
          </p>
        </div>
      </div>

      <div className="workspace-create">
        <div className="workspace-create__heading">
          <FolderPlus size={19} aria-hidden="true" />
          <div>
            <h4>创建或重新关联工作区</h4>
            <p>名称可以稍后修改；留空时使用文件夹名称。</p>
          </div>
        </div>
        <div className="workspace-create__fields">
          <Field
            label="本地文件夹路径"
            name="workspacePath"
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
            placeholder="/Users/you/interview-workspace"
          />
          <Field
            label="工作区名称（可选）"
            name="workspaceDisplayName"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="例如：后端岗位准备"
          />
        </div>
        <Button onClick={() => void createWorkspace()} loading={busyId === "create"}>
          创建工作区
        </Button>
      </div>

      <div className="workspace-manager__section">
        <div className="workspace-manager__section-heading">
          <div>
            <h4>可用工作区</h4>
            <p>{activeItems.length} 个，可随时切换</p>
          </div>
        </div>
        {loading ? <p className="status-note">正在读取工作区…</p> : null}
        {!loading && activeItems.length === 0 ? (
          <div className="settings-guidance">还没有可用工作区，请先创建。</div>
        ) : null}
        <div className="workspace-list">
          {activeItems.map((resource) => {
            const current = resource.id === workspace?.id || resource.isCurrent;
            const mustSwitchFirst = current && activeItems.length > 1;
            return (
              <article className="workspace-item" key={resource.id}>
                <div className="workspace-item__main">
                  <div className="workspace-item__title-row">
                    {editingId === resource.id ? (
                      <div className="workspace-item__rename">
                        <label htmlFor={`workspace-name-${resource.id}`}>工作区名称</label>
                        <input
                          id={`workspace-name-${resource.id}`}
                          className="field__input"
                          value={editingName}
                          onChange={(event) => setEditingName(event.target.value)}
                          autoFocus
                        />
                      </div>
                    ) : (
                      <h5>{resource.displayName}</h5>
                    )}
                    {current ? <Badge tone="primary"><Check size={13} />当前</Badge> : null}
                    {resource.activeExecutionCount > 0 ? (
                      <Badge tone="warning" dot>
                        {resource.activeExecutionCount} 个任务运行中
                      </Badge>
                    ) : null}
                  </div>
                  <p className="workspace-item__path" title={resource.rootPath}>
                    {resource.rootPath}
                  </p>
                  {mustSwitchFirst ? (
                    <p className="workspace-item__constraint">
                      先切换到其他工作区，才能将当前工作区移入回收站。
                    </p>
                  ) : resource.activeExecutionCount > 0 ? (
                    <p className="workspace-item__constraint">
                      先暂停或终止运行中的任务，才能移入回收站。
                    </p>
                  ) : null}
                </div>
                <div className="workspace-item__actions">
                  {editingId === resource.id ? (
                    <>
                      <Button size="sm" onClick={() => void saveName(resource)} loading={busyId === resource.id}>保存</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>取消</Button>
                    </>
                  ) : (
                    <>
                      {!current ? (
                        <Button size="sm" variant="secondary" onClick={() => void chooseWorkspace(resource)} loading={busyId === resource.id}>切换</Button>
                      ) : null}
                      <Button size="sm" variant="ghost" onClick={() => {
                        setEditingId(resource.id);
                        setEditingName(resource.displayName);
                      }}>
                        <Pencil size={14} aria-hidden="true" />
                        重命名
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={mustSwitchFirst || resource.activeExecutionCount > 0}
                        onClick={() => setRecycleConfirmId(resource.id)}
                        title={
                          mustSwitchFirst
                            ? "请先切换到其他工作区"
                            : resource.activeExecutionCount > 0
                              ? "请先暂停或终止运行中的任务"
                              : undefined
                        }
                      >
                        <Trash2 size={14} aria-hidden="true" />
                        移入回收站
                      </Button>
                    </>
                  )}
                </div>
                {recycleConfirmId === resource.id ? (
                  <div className="workspace-item__confirm">
                    <p>移入回收站后将从切换列表隐藏，但仍可恢复。</p>
                    <div className="btn-row">
                      <Button size="sm" variant="danger" onClick={() => void recycle(resource)} loading={busyId === resource.id}>确认移入回收站</Button>
                      <Button size="sm" variant="ghost" onClick={() => setRecycleConfirmId(null)}>取消</Button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </div>

      <div className="workspace-manager__section">
        <div className="workspace-manager__section-heading">
          <div>
            <h4>回收站</h4>
            <p>{recycledItems.length} 个工作区</p>
          </div>
        </div>
        {recycledItems.length === 0 ? (
          <p className="status-note">回收站为空</p>
        ) : (
          <div className="workspace-list">
            {recycledItems.map((resource) => (
              <article className="workspace-item workspace-item--recycled" key={resource.id}>
                <div className="workspace-item__main">
                  <h5>{resource.displayName}</h5>
                  <p className="workspace-item__path">{resource.rootPath}</p>
                </div>
                <div className="workspace-item__actions">
                  <Button size="sm" variant="secondary" onClick={() => void restore(resource)} loading={busyId === resource.id}>
                    <ArchiveRestore size={14} aria-hidden="true" />
                    恢复
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => void preparePermanentDelete(resource)} loading={busyId === resource.id}>
                    永久删除
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {deleteImpact ? (
        <div className="workspace-delete-impact" role="alertdialog" aria-labelledby="workspace-delete-title">
          <div>
            <h4 id="workspace-delete-title">永久删除“{deleteImpact.displayName}”</h4>
            <p>
              将删除 {deleteImpact.sessionCount} 个会话、{deleteImpact.materialCount} 份资料、
              {deleteImpact.questionCount} 道题和 {deleteImpact.jobTargetCount} 个求职目标。
              本机 Vault 文件夹会保留。
            </p>
          </div>
          <label htmlFor="workspace-delete-confirmation">
            输入 <strong>DELETE {deleteImpact.displayName}</strong> 确认
          </label>
          <input
            id="workspace-delete-confirmation"
            className="field__input"
            value={deleteConfirmation}
            onChange={(event) => setDeleteConfirmation(event.target.value)}
            autoComplete="off"
          />
          <div className="btn-row">
            <Button
              variant="danger"
              disabled={deleteConfirmation !== `DELETE ${deleteImpact.displayName}`}
              loading={busyId === deleteImpact.workspaceId}
              onClick={() => void deletePermanently()}
            >
              永久删除应用数据
            </Button>
            <Button variant="ghost" onClick={() => {
              setDeleteImpact(null);
              setDeleteConfirmation("");
            }}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="error-banner" role="alert" aria-live="polite">
          <AlertCircle size={16} aria-hidden="true" />
          <span>错误：{error.message}</span>
          <span>{error.advice}</span>
          <Button size="sm" variant="ghost" onClick={() => {
            setError(null);
            void refresh();
          }}>
            <RotateCcw size={14} aria-hidden="true" />
            重新读取
          </Button>
        </div>
      ) : null}
    </section>
  );
}
