import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Save, Send } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { toActionableError, type ActionableError } from "../../shared/api/errorAdvice";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { listDrafts, requestPublication, updateDraft } from "./draftApi";
import type { KnowledgeDraftStatus } from "./draftTypes";

const STATUS_TONE: Record<KnowledgeDraftStatus, "neutral" | "warning" | "danger" | "success"> = {
  draft: "neutral",
  review_pending: "warning",
  rejected: "danger",
  published: "success",
};

const STATUS_LABEL: Record<KnowledgeDraftStatus, string> = {
  draft: "草稿",
  review_pending: "等待确认",
  rejected: "已拒绝",
  published: "已发布",
};

interface DraftReviewProps {
  workspaceId: string;
  onPublicationRequested?: (runId: string) => void;
}

export function DraftReview({ workspaceId, onPublicationRequested }: DraftReviewProps) {
  const queryClient = useQueryClient();
  const queryKey = ["knowledge-drafts", workspaceId] as const;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<ActionableError | null>(null);

  const draftsQuery = useQuery({
    queryKey,
    queryFn: () => listDrafts(workspaceId),
  });
  const drafts = draftsQuery.data ?? [];
  const selected = useMemo(
    () => drafts.find((item) => item.id === selectedId) ?? drafts[0] ?? null,
    [drafts, selectedId],
  );

  // Reset the editor to the selected draft whenever the draft identity or its
  // version changes (version changes after a successful save or after a 409
  // reload, so the editor picks up the server's latest content).
  useEffect(() => {
    if (!selected) {
      setTitle("");
      setMarkdown("");
      return;
    }
    setSelectedId(selected.id);
    setTitle(selected.title);
    setMarkdown(selected.markdown);
  }, [selected?.id, selected?.version]);

  const editable = selected?.status === "draft" || selected?.status === "review_pending";

  const saveMutation = useMutation({
    mutationFn: () =>
      updateDraft(selected!.id, { version: selected!.version, title, markdown }),
    onMutate: () => {
      setMessage(null);
      setError(null);
    },
    onSuccess: () => {
      setMessage("草稿已保存");
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.code === "draft_version_changed") {
        queryClient.invalidateQueries({ queryKey });
        setError(
          toActionableError(new Error("草稿已被其他操作更新，已自动刷新"), "保存失败"),
        );
      } else {
        setError(toActionableError(caught, "保存失败"));
      }
    },
  });

  const publishMutation = useMutation({
    mutationFn: () => requestPublication(selected!.id),
    onMutate: () => {
      setMessage(null);
      setError(null);
    },
    onSuccess: (run) => {
      setMessage("已请求发布，等待人工确认");
      queryClient.invalidateQueries({ queryKey });
      onPublicationRequested?.(run.runId);
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.code === "external_document_changed") {
        setError(
          toActionableError(
            new Error("Vault 文档已被外部修改，请先处理冲突"),
            "发布失败",
          ),
        );
      } else {
        setError(toActionableError(caught, "发布失败"));
      }
    },
  });

  const busy = saveMutation.isPending || publishMutation.isPending;

  return (
    <Card title="草稿审核" icon={<FileText size={18} />} ariaLabel="草稿审核">
      <div className="draft-review" aria-live="polite">
        {draftsQuery.isLoading ? <p className="status-note">正在读取草稿…</p> : null}
        {!draftsQuery.isLoading && drafts.length === 0 ? (
          <p className="status-note">暂无草稿，上传资料后会自动生成</p>
        ) : null}

        {drafts.length > 0 ? (
          <div className="draft-review__list" role="list" aria-label="知识草稿">
            {drafts.map((item) => (
              <button
                key={item.id}
                type="button"
                className="draft-review__list-item"
                aria-current={selected?.id === item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <span>{item.title}</span>
                <Badge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Badge>
              </button>
            ))}
          </div>
        ) : null}

        {selected ? (
          <div className="draft-review__detail">
            <div className="draft-review__meta">
              <Badge tone={STATUS_TONE[selected.status]} dot>{STATUS_LABEL[selected.status]}</Badge>
              <span>版本 {selected.version}</span>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="draftTitle">标题</label>
              <input
                id="draftTitle"
                name="draftTitle"
                className="field__input"
                value={title}
                disabled={!editable || busy}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor="draftMarkdown">Markdown 正文</label>
              <textarea
                id="draftMarkdown"
                name="draftMarkdown"
                className="field__input field__input--textarea"
                rows={8}
                value={markdown}
                disabled={!editable || busy}
                onChange={(event) => setMarkdown(event.target.value)}
              />
            </div>

            {selected.status === "published" && selected.publication ? (
              <p className="status-note">
                已发布路径：knowledge-vault/{selected.publication.targetPath}
              </p>
            ) : null}
            {selected.publication?.state === "index_stale" ? (
              <p className="status-note status-note--warning">
                Markdown 已发布，但索引尚未更新；请运行“重新扫描 Vault”修复。
              </p>
            ) : null}
            {selected.status === "review_pending" ? (
              <p className="status-note">等待人工确认，批准后会发布到 Vault</p>
            ) : null}
            {selected.status === "rejected" ? (
              <p className="status-note">该草稿已被拒绝，重新上传资料可生成新草稿</p>
            ) : null}

            <div className="btn-row">
              <Button
                onClick={() => saveMutation.mutate()}
                loading={saveMutation.isPending}
                disabled={!editable || busy}
              >
                <Save size={16} aria-hidden="true" />
                保存草稿
              </Button>
              <Button
                variant="secondary"
                onClick={() => publishMutation.mutate()}
                loading={publishMutation.isPending}
                disabled={!editable || busy}
              >
                <Send size={16} aria-hidden="true" />
                请求发布
              </Button>
            </div>
          </div>
        ) : null}

        {message ? <p className="status-note">{message}</p> : null}
        {error ? (
          <div className="error-banner" role="alert" aria-live="polite">
            <span>错误：{error.message}</span>
            <span>下一步：{error.advice}</span>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
