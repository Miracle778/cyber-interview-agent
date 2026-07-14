import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookOpen, File, FileText, FolderLock, RefreshCw, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { DraftReview } from "./DraftReview";
import { listDrafts } from "./draftApi";
import type { KnowledgeDraftStatus } from "./draftTypes";
import { listSources, rescanVault, uploadSource } from "./knowledgeApi";

interface KnowledgePageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  onDraftQuestionReady: (question: ReviewQuestion) => void;
  onVaultRescanned: (indexedCount: number) => void;
}

type ResourceSelection =
  | { kind: "source"; id: string }
  | { kind: "draft"; id: string }
  | null;

const STATUS_LABEL: Record<KnowledgeDraftStatus, string> = {
  draft: "草稿",
  review_pending: "等待确认",
  rejected: "已拒绝",
  published: "已发布",
};

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export function KnowledgePage({ workspace, onDraftQuestionReady, onVaultRescanned }: KnowledgePageProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selection, setSelection] = useState<ResourceSelection>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRescanning, setIsRescanning] = useState(false);
  const [publicationExecutionId, setPublicationExecutionId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const workspaceId = workspace?.id ?? "";
  const hasWorkspace = workspace !== null;

  const sourcesQuery = useQuery({
    queryKey: ["knowledge-sources", workspaceId],
    queryFn: () => listSources(workspaceId),
    enabled: hasWorkspace,
  });
  const draftsQuery = useQuery({
    queryKey: ["knowledge-drafts", workspaceId],
    queryFn: () => listDrafts(workspaceId),
    enabled: hasWorkspace,
  });
  const sources = useMemo(() => sourcesQuery.data ?? [], [sourcesQuery.data]);
  const drafts = useMemo(() => draftsQuery.data ?? [], [draftsQuery.data]);

  useEffect(() => {
    if (!workspace) {
      setSelection(null);
      return;
    }
    setSelection((current) => {
      const currentExists = current?.kind === "source"
        ? sources.some((item) => item.id === current.id)
        : current?.kind === "draft"
          ? drafts.some((item) => item.id === current.id)
          : false;
      if (currentExists) return current;
      if (drafts[0]) return { kind: "draft", id: drafts[0].id };
      if (sources[0]) return { kind: "source", id: sources[0].id };
      return null;
    });
  }, [drafts, sources, workspace]);

  const selectedSource = selection?.kind === "source"
    ? sources.find((item) => item.id === selection.id) ?? null
    : null;

  function selectResource(next: Exclude<ResourceSelection, null>) {
    if (selection?.kind === next.kind && selection.id === next.id) return true;
    if (draftDirty && !globalThis.confirm("放弃未保存的修改？")) return false;
    setDraftDirty(false);
    setSelection(next);
    return true;
  }

  async function handleUpload() {
    setError(null);
    if (!workspace) {
      setError(toActionableError(new Error("请先初始化工作区"), "上传失败"));
      return;
    }
    if (!selectedFile) {
      setError(toActionableError(new Error("请选择资料文件"), "上传失败"));
      return;
    }
    setIsUploading(true);
    try {
      const result = await uploadSource(workspace.id, selectedFile);
      selectResource({ kind: "source", id: result.source.id });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] }),
        queryClient.invalidateQueries({ queryKey: ["knowledge-drafts", workspace.id] }),
      ]);
    } catch (caught) {
      setError(toActionableError(caught, "上传失败"));
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRescan() {
    setError(null);
    if (!workspace) {
      setError(toActionableError(new Error("请先初始化工作区"), "重新扫描失败"));
      return;
    }
    setIsRescanning(true);
    try {
      const result = await rescanVault(workspace.id);
      setIndexedCount(result.indexed);
      onVaultRescanned(result.indexed);
    } catch (caught) {
      setError(toActionableError(caught, "重新扫描失败"));
    } finally {
      setIsRescanning(false);
    }
  }

  function handlePublicationResolved() {
    if (!workspace) return;
    queryClient.invalidateQueries({ queryKey: ["knowledge-drafts", workspace.id] });
    queryClient.invalidateQueries({ queryKey: ["pending-actions", workspace.id] });
    setPublicationExecutionId(null);
  }

  return (
    <section className="page-section" aria-labelledby="knowledge-title">
      <div className="page-section__header">
        <span className="page-section__icon" aria-hidden="true"><BookOpen size={18} /></span>
        <h2 id="knowledge-title" className="page-section__title">知识文档</h2>
        {hasWorkspace ? <span className="page-section__hint">管理资料、草稿和发布状态</span> : null}
      </div>

      <Card className="knowledge-toolbar" ariaLabel="知识库工具栏">
        {!hasWorkspace ? (
          <div className="empty-state">
            <span className="empty-state__icon" aria-hidden="true"><FolderLock size={20} /></span>
            <p className="empty-state__text">请先初始化工作区</p>
            <Link className="text-link" to="/settings">前往设置</Link>
          </div>
        ) : null}
        <div className="knowledge-toolbar__controls">
          <label className="file-field" htmlFor="sourceFile">
            <span className="file-field__label">选择资料文件</span>
            <input
              id="sourceFile"
              name="sourceFile"
              type="file"
              className="file-field__input"
              disabled={!hasWorkspace || isUploading}
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <div className="btn-row">
            <Button onClick={handleUpload} disabled={!hasWorkspace || isUploading} loading={isUploading}>
              <Upload size={16} aria-hidden="true" />上传资料
            </Button>
            <Button variant="secondary" onClick={handleRescan} disabled={!hasWorkspace || isRescanning} loading={isRescanning}>
              <RefreshCw size={16} aria-hidden="true" />重新扫描 Vault
            </Button>
            {indexedCount !== null ? <span className="status-note">索引文档数：{indexedCount}</span> : null}
          </div>
        </div>
      </Card>

      {hasWorkspace ? (
        <div className="knowledge-workspace">
          <nav className="knowledge-resources" aria-label="知识库资源">
            <section className="resource-group" aria-labelledby="source-group-title">
              <div className="resource-group__heading">
                <File size={16} aria-hidden="true" />
                <h3 id="source-group-title">原始资料</h3>
                <span>{sources.length}</span>
              </div>
              {sourcesQuery.isLoading ? <p className="status-note">正在读取资料…</p> : null}
              {sourcesQuery.isError ? (
                <div className="resource-error" role="alert">
                  <p>资料读取失败</p>
                  <Button size="sm" variant="ghost" onClick={() => sourcesQuery.refetch()}>
                    重试读取资料
                  </Button>
                </div>
              ) : null}
              {!sourcesQuery.isLoading && !sourcesQuery.isError && sources.length === 0 ? <p className="status-note">尚未上传资料</p> : null}
              {sources.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="resource-item"
                  aria-current={selection?.kind === "source" && selection.id === item.id}
                  onClick={() => selectResource({ kind: "source", id: item.id })}
                >
                  <span className="resource-item__title">{item.originalFilename}</span>
                  <span className="resource-item__meta">{formatBytes(item.sizeBytes)}</span>
                </button>
              ))}
            </section>

            <section className="resource-group" aria-labelledby="draft-group-title">
              <div className="resource-group__heading">
                <FileText size={16} aria-hidden="true" />
                <h3 id="draft-group-title">生成草稿</h3>
                <span>{drafts.length}</span>
              </div>
              {draftsQuery.isLoading ? <p className="status-note">正在读取草稿…</p> : null}
              {!draftsQuery.isLoading && drafts.length === 0 ? <p className="status-note">题库整理或 Agent 报告生成后显示</p> : null}
              {drafts.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="resource-item"
                  aria-current={selection?.kind === "draft" && selection.id === item.id}
                  onClick={() => selectResource({ kind: "draft", id: item.id })}
                >
                  <span className="resource-item__title">{item.title}</span>
                  <span className="resource-item__meta">{STATUS_LABEL[item.status]}</span>
                </button>
              ))}
            </section>
          </nav>

          <section className="knowledge-detail" aria-label="知识内容">
            {selection?.kind === "draft" ? (
              <DraftReview
                workspaceId={workspace.id}
                selectedId={selection.id}
                onSelectedIdChange={(id) => setSelection({ kind: "draft", id })}
                onDirtyChange={setDraftDirty}
                showList={false}
                onPublicationRequested={setPublicationExecutionId}
              />
            ) : null}
            {selectedSource ? (
              <Card title={selectedSource.originalFilename} icon={<File size={18} />}>
                <dl className="source-detail">
                  <div><dt>文件类型</dt><dd>{selectedSource.contentType}</dd></div>
                  <div><dt>文件大小</dt><dd>{formatBytes(selectedSource.sizeBytes)}</dd></div>
                  <div><dt>上传时间</dt><dd>{formatDate(selectedSource.createdAt)}</dd></div>
                  <div><dt>存储位置</dt><dd>{selectedSource.storedPath}</dd></div>
                </dl>
                {selectedSource.draftId ? (
                  <Button variant="secondary" onClick={() => selectResource({ kind: "draft", id: selectedSource.draftId! })}>
                    查看关联草稿
                  </Button>
                ) : null}
              </Card>
            ) : null}
            {!selection && !draftsQuery.isLoading && !sourcesQuery.isLoading ? (
              <Card>
                <div className="empty-state">
                  <span className="empty-state__icon" aria-hidden="true"><FileText size={20} /></span>
                  <p className="empty-state__text">上传第一份资料，开始建立知识库</p>
                </div>
              </Card>
            ) : null}
          </section>
        </div>
      ) : null}

      {hasWorkspace ? (
        <ActionCenter
          workspaceId={workspace.id}
          showDiagnostic={false}
          actionType="knowledge.publish"
          watchExecutionId={publicationExecutionId}
          onResolved={handlePublicationResolved}
        />
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
