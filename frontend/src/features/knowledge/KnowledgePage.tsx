import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookOpen, ChevronDown, File, FileText, FolderLock, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { DraftReview } from "./DraftReview";
import { listDrafts } from "./draftApi";
import type { KnowledgeDraftStatus } from "./draftTypes";
import { deleteSource, listSources, rescanVault, uploadSource } from "./knowledgeApi";

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
  superseded: "已替代",
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

function contentTypeLabel(value: string) {
  if (value === "text/markdown") return "Markdown 文档";
  if (value === "text/plain") return "文本文档";
  if (value === "application/pdf") return "PDF 文档";
  return "资料文件";
}

export function KnowledgePage({ workspace, onDraftQuestionReady, onVaultRescanned }: KnowledgePageProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [resourceQuery, setResourceQuery] = useState("");
  const [selection, setSelection] = useState<ResourceSelection>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRescanning, setIsRescanning] = useState(false);
  const [publicationExecutionId, setPublicationExecutionId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
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
  const normalizedQuery = resourceQuery.trim().toLocaleLowerCase("zh-CN");
  const filteredSources = useMemo(
    () => normalizedQuery
      ? sources.filter((item) => item.originalFilename.toLocaleLowerCase("zh-CN").includes(normalizedQuery))
      : sources,
    [normalizedQuery, sources],
  );
  const filteredDrafts = useMemo(
    () => normalizedQuery
      ? drafts.filter((item) => item.title.toLocaleLowerCase("zh-CN").includes(normalizedQuery))
      : drafts,
    [drafts, normalizedQuery],
  );

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

  async function handleDeleteSource() {
    if (!workspace || !selectedSource) return;
    if (!globalThis.confirm("将原材料移到回收站？已生成题目和来源依据不会受影响。")) return;
    setError(null);
    try {
      await deleteSource(workspace.id, selectedSource.id, false);
      setSelection(null);
      await queryClient.invalidateQueries({ queryKey: ["knowledge-sources", workspace.id] });
    } catch (caught) {
      setError(toActionableError(caught, "删除资料失败"));
    }
  }

  function handlePublicationResolved() {
    if (!workspace) return;
    queryClient.invalidateQueries({ queryKey: ["knowledge-drafts", workspace.id] });
    queryClient.invalidateQueries({ queryKey: ["pending-actions", workspace.id] });
    setPublicationExecutionId(null);
  }

  return (
    <section className="page-section knowledge-page" aria-label="知识库内容">
      <Card className="knowledge-toolbar" ariaLabel="知识库工具栏">
        {!hasWorkspace ? (
          <div className="empty-state">
            <span className="empty-state__icon" aria-hidden="true"><FolderLock size={20} /></span>
            <p className="empty-state__text">请先初始化工作区</p>
            <Link className="text-link" to="/settings">前往设置</Link>
          </div>
        ) : null}
        <div className="knowledge-toolbar__controls">
          <details className="knowledge-upload">
            <summary>
              <Upload size={16} aria-hidden="true" />
              添加资料
              <ChevronDown className="knowledge-upload__chevron" size={16} aria-hidden="true" />
            </summary>
            <div className="knowledge-upload__body">
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
              <Button onClick={handleUpload} disabled={!hasWorkspace || isUploading} loading={isUploading}>
                <Upload size={16} aria-hidden="true" />上传资料
              </Button>
            </div>
          </details>
          <Button variant="secondary" onClick={handleRescan} disabled={!hasWorkspace || isRescanning} loading={isRescanning}>
            <RefreshCw size={16} aria-hidden="true" />刷新资料
          </Button>
          {indexedCount !== null ? <span className="status-note">已刷新 {indexedCount} 份资料</span> : null}
          {hasWorkspace ? (
            <span className="knowledge-toolbar__summary">
              {sources.length} 份资料 · {drafts.length} 条整理结果
            </span>
          ) : null}
        </div>
      </Card>

      {hasWorkspace ? (
        <div className="knowledge-workspace">
          <nav className="knowledge-resources" aria-label="知识库资源">
            <label className="knowledge-search" htmlFor="knowledgeResourceSearch">
              <Search size={16} aria-hidden="true" />
              <input
                id="knowledgeResourceSearch"
                type="search"
                value={resourceQuery}
                onChange={(event) => setResourceQuery(event.target.value)}
                placeholder="搜索资料或整理结果"
              />
            </label>
            <section className="resource-group" aria-labelledby="source-group-title">
              <div className="resource-group__heading">
                <File size={16} aria-hidden="true" />
                <h3 id="source-group-title">导入资料</h3>
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
              {!sourcesQuery.isLoading && sources.length > 0 && filteredSources.length === 0 ? <p className="status-note">没有匹配的导入资料</p> : null}
              {filteredSources.map((item) => (
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
                <h3 id="draft-group-title">整理结果</h3>
                <span>{drafts.length}</span>
              </div>
              {draftsQuery.isLoading ? <p className="status-note">正在读取草稿…</p> : null}
              {!draftsQuery.isLoading && drafts.length === 0 ? <p className="status-note">题库整理或 Agent 报告生成后显示</p> : null}
              {!draftsQuery.isLoading && drafts.length > 0 && filteredDrafts.length === 0 ? <p className="status-note">没有匹配的整理结果</p> : null}
              {filteredDrafts.map((item) => (
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
                  <div><dt>文件类型</dt><dd>{contentTypeLabel(selectedSource.contentType)}</dd></div>
                  <div><dt>文件大小</dt><dd>{formatBytes(selectedSource.sizeBytes)}</dd></div>
                  <div><dt>上传时间</dt><dd>{formatDate(selectedSource.createdAt)}</dd></div>
                  <div><dt>整理状态</dt><dd>{selectedSource.draftId ? "已生成整理草稿" : "等待整理"}</dd></div>
                </dl>
                {selectedSource.draftId ? (
                  <Button variant="secondary" onClick={() => selectResource({ kind: "draft", id: selectedSource.draftId! })}>
                    查看关联草稿
                  </Button>
                ) : null}
                {!selectedSource.draftId ? <div className="source-next-step"><div><strong>下一步：整理成可复习题目</strong><p>进入题库整理后选择这份资料，系统会保留处理进度和来源位置。</p></div><Button onClick={() => navigate("/review")}><BookOpen size={16} />去整理题目</Button></div> : null}
                <div className="source-delete-actions">
                  <Button variant="secondary" onClick={() => void handleDeleteSource()}><Trash2 size={16} />移到回收站</Button>
                </div>
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
