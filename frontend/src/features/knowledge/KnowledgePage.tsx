import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookOpen, FileText, FolderLock, RefreshCw, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { ActionCenter } from "../agent/ActionCenter";
import type { ReviewQuestion, MasteryState } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { rescanVault, uploadSource } from "./knowledgeApi";
import { DraftReview } from "./DraftReview";

interface KnowledgePageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  onDraftQuestionReady: (question: ReviewQuestion) => void;
  onVaultRescanned: (indexedCount: number) => void;
}

const MASTERY_TONE: Record<MasteryState, "neutral" | "danger" | "warning" | "primary" | "success"> = {
  unknown: "neutral",
  weak: "danger",
  partial: "warning",
  stable: "primary",
  strong: "success",
};

export function KnowledgePage({ workspace, draftQuestion, onDraftQuestionReady, onVaultRescanned }: KnowledgePageProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [visibleDraftQuestion, setVisibleDraftQuestion] = useState<ReviewQuestion | null>(draftQuestion);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRescanning, setIsRescanning] = useState(false);
  const [publicationRunId, setPublicationRunId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const hasWorkspace = workspace !== null;

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
      const question = result.question;
      setVisibleDraftQuestion(question);
      onDraftQuestionReady(question);
      queryClient.invalidateQueries({ queryKey: ["knowledge-drafts", workspace.id] });
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

  const questionToDisplay = visibleDraftQuestion ?? draftQuestion;

  function handlePublicationResolved() {
    if (!workspace) return;
    queryClient.invalidateQueries({ queryKey: ["knowledge-drafts", workspace.id] });
    queryClient.invalidateQueries({ queryKey: ["pending-actions", workspace.id] });
    setPublicationRunId(null);
  }

  return (
    <section className="page-section" aria-labelledby="knowledge-title">
      <div className="page-section__header">
        <span className="page-section__icon" aria-hidden="true">
          <BookOpen size={18} />
        </span>
        <h2 id="knowledge-title" className="page-section__title">
          知识文档
        </h2>
        {hasWorkspace ? <span className="page-section__hint">上传资料自动生成题库草稿</span> : null}
      </div>

      <Card title="资料上传" icon={<Upload size={18} />}>
        {!hasWorkspace ? (
          <div className="empty-state">
            <span className="empty-state__icon" aria-hidden="true">
              <FolderLock size={20} />
            </span>
            <p className="empty-state__text">请先初始化工作区</p>
            <Link className="text-link" to="/settings">
              前往设置
            </Link>
          </div>
        ) : null}

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
            <Upload size={16} aria-hidden="true" />
            上传资料
          </Button>
          <Button
            variant="secondary"
            onClick={handleRescan}
            disabled={!hasWorkspace || isRescanning}
            loading={isRescanning}
          >
            <RefreshCw size={16} aria-hidden="true" />
            重新扫描 Vault
          </Button>
          {indexedCount !== null ? (
            <span className="status-note">索引文档数：{indexedCount}</span>
          ) : null}
        </div>
      </Card>

      {questionToDisplay ? (
        <Card title="题库草稿" icon={<FileText size={18} />} ariaLabel="题库草稿">
          <h3 className="question-card__title">{questionToDisplay.title}</h3>
          <p className="question-card__text">{questionToDisplay.questionText}</p>

          <div>
            <p className="muted-text" style={{ marginBottom: "var(--space-2)" }}>
              参考答案
            </p>
            <pre className="reference-block">{questionToDisplay.referenceAnswer}</pre>
          </div>

          <div className="meta-row">
            <span>
              主题：
              {questionToDisplay.topics.length ? (
                questionToDisplay.topics.map((topic) => (
                  <span className="tag" key={topic}>
                    {topic}
                  </span>
                ))
              ) : (
                <span className="muted-text">未标记</span>
              )}
            </span>
          </div>

          <div className="meta-row">
            <span>
              难度：<Badge tone="primary">{questionToDisplay.difficulty}</Badge>
            </span>
            <span>
              掌握度：<Badge tone={MASTERY_TONE[questionToDisplay.mastery]}>{questionToDisplay.mastery}</Badge>
            </span>
          </div>

          <p className="eval-line">关键点：{questionToDisplay.keyPoints.join("、") || "无"}</p>
        </Card>
      ) : (
        <Card>
          <div className="empty-state">
            <span className="empty-state__icon" aria-hidden="true">
              <FileText size={20} />
            </span>
            <p className="empty-state__text">暂无文档</p>
          </div>
        </Card>
      )}

      {hasWorkspace ? (
        <>
          <DraftReview
            workspaceId={workspace!.id}
            onPublicationRequested={setPublicationRunId}
          />
          <ActionCenter
            workspaceId={workspace!.id}
            showDiagnostic={false}
            actionType="knowledge.publish"
            watchRunId={publicationRunId}
            onResolved={handlePublicationResolved}
          />
        </>
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
