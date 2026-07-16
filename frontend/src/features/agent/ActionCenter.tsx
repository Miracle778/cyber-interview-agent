import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, PencilLine, Play, ShieldQuestion, X } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { Field } from "../../shared/ui/Field";
import { MarkdownView } from "../knowledge/MarkdownView";
import {
  createAgentSession,
  listAgentSessions,
  startAgentExecution,
} from "./agentApi";
import { approveAction, listActions, rejectAction } from "./hitlApi";
import type { PendingAction } from "./hitlTypes";


const KIND = "diagnostic.approval";
const SESSION_TITLE = "人工确认自检";


function displayValue(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value);
}


function operationKey(kind: "approve" | "reject", actionId: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `${kind}-${actionId}-${random}`;
}

function editValue(action: PendingAction, field: string, edits: Record<string, string>) {
  return edits[field] ?? displayValue(action.preview[field] ?? "");
}


async function waitForPendingAction(workspaceId: string, executionId: string) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const actions = await listActions(workspaceId, { status: "pending" });
    if (actions.some((action) => action.executionId === executionId)) return actions;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("确认测试已启动，但待确认动作尚未出现");
}


export interface ActionCenterProps {
  workspaceId: string;
  /** Show the diagnostic "运行确认测试" button. Defaults to true (settings page). */
  showDiagnostic?: boolean;
  /** Restrict the list to a single action type, e.g. "knowledge.publish". */
  actionType?: string;
  /** Poll until the pending action produced by this run appears. */
  watchExecutionId?: string | null;
  /** Notify the owning page after approve/reject delivery finishes. */
  onResolved?: () => void;
  /** Use the focused publication review layout instead of the generic card. */
  presentation?: "default" | "publication";
}

export function ActionCenter({
  workspaceId,
  showDiagnostic = true,
  actionType,
  watchExecutionId,
  onResolved,
  presentation = "default",
}: ActionCenterProps) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["pending-actions", workspaceId] as const,
    [workspaceId],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [showRejectReason, setShowRejectReason] = useState(false);
  const [watchAttempt, setWatchAttempt] = useState(0);
  const operationKeys = useRef(new Map<string, string>());

  const actionsQuery = useQuery({
    queryKey,
    queryFn: () => listActions(workspaceId, { status: "pending" }),
  });
  const allActions = actionsQuery.data ?? [];
  const actions = allActions.filter((item) =>
    (!actionType || item.actionType === actionType)
    && (!watchExecutionId || item.executionId === watchExecutionId),
  );
  const selected = useMemo(
    () => actions.find((item) => item.id === selectedId) ?? actions[0] ?? null,
    [actions, selectedId],
  );

  useEffect(() => {
    if (!selected) {
      setEdits({});
      return;
    }
    setSelectedId(selected.id);
    setEdits(
      Object.fromEntries(
        selected.editableFields.map((field) => [
          field,
          displayValue(selected.preview[field] ?? ""),
        ]),
      ),
    );
    setReason("");
    setShowRejectReason(false);
  }, [selected?.id]);

  useEffect(() => {
    if (!watchExecutionId) {
      setLocalError(null);
      return;
    }
    let cancelled = false;
    waitForPendingAction(workspaceId, watchExecutionId)
      .then((pending) => {
        if (!cancelled) queryClient.setQueryData(queryKey, pending);
      })
      .catch((error) => {
        if (!cancelled) {
          setLocalError(error instanceof Error ? error.message : "待确认动作尚未出现");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [queryClient, queryKey, watchAttempt, watchExecutionId, workspaceId]);

  const runMutation = useMutation({
    mutationFn: async () => {
      const sessions = await listAgentSessions(workspaceId);
      let session = sessions.find(
        (item) => item.kind === KIND,
      );
      if (!session) {
        session = await createAgentSession({
          workspaceId,
          kind: KIND,
          title: SESSION_TITLE,
        });
      }
      const run = await startAgentExecution(session.id, { summary: "请确认这次操作" });
      return waitForPendingAction(workspaceId, run.id);
    },
    onMutate: () => {
      setMessage(null);
      setLocalError(null);
    },
    onSuccess: (pending) => queryClient.setQueryData(queryKey, pending),
    onError: (error) =>
      setLocalError(error instanceof Error ? error.message : "无法运行确认测试"),
  });

  const approveMutation = useMutation({
    mutationFn: async (action: PendingAction) => {
      const changed = Object.fromEntries(
        action.editableFields
          .filter((field) => editValue(action, field, edits) !== displayValue(action.preview[field] ?? ""))
          .map((field) => [field, editValue(action, field, edits)]),
      );
      const keyName = `approve:${action.id}:${JSON.stringify({
        version: action.version,
        editedPayload: changed,
      })}`;
      let key = operationKeys.current.get(keyName);
      if (!key) {
        key = operationKey("approve", action.id);
        operationKeys.current.set(keyName, key);
      }
      return approveAction(action.id, {
        version: action.version,
        idempotencyKey: key,
        ...(Object.keys(changed).length > 0 ? { editedPayload: changed } : {}),
      });
    },
    onMutate: () => {
      setMessage(null);
      setLocalError(null);
    },
    onSuccess: (resolved) => {
      queryClient.setQueryData<PendingAction[]>(queryKey, (current = []) =>
        current.filter((item) => item.id !== resolved.id),
      );
      setMessage("确认动作已批准");
      onResolved?.();
    },
    onError: (error) =>
      setLocalError(
        error instanceof ApiError && error.code === "action_version_conflict"
          ? "内容已更新，请刷新后重新确认"
          : error instanceof Error
            ? error.message
            : "批准失败",
      ),
  });

  const rejectMutation = useMutation({
    mutationFn: async (action: PendingAction) => {
      if (!reason.trim()) throw new Error("请填写拒绝原因");
      const normalizedReason = reason.trim();
      const keyName = `reject:${action.id}:${JSON.stringify({
        version: action.version,
        reason: normalizedReason,
      })}`;
      let key = operationKeys.current.get(keyName);
      if (!key) {
        key = operationKey("reject", action.id);
        operationKeys.current.set(keyName, key);
      }
      return rejectAction(action.id, {
        version: action.version,
        idempotencyKey: key,
        reason: normalizedReason,
      });
    },
    onMutate: () => {
      setMessage(null);
      setLocalError(null);
    },
    onSuccess: (resolved) => {
      queryClient.setQueryData<PendingAction[]>(queryKey, (current = []) =>
        current.filter((item) => item.id !== resolved.id),
      );
      setMessage("确认动作已拒绝");
      onResolved?.();
    },
    onError: (error) =>
      setLocalError(error instanceof Error ? error.message : "拒绝失败"),
  });

  const resolving = approveMutation.isPending || rejectMutation.isPending;
  const waitingForAction = Boolean(watchExecutionId) && actions.length === 0 && !localError;
  const hidden = !showDiagnostic
    && actions.length === 0
    && !waitingForAction
    && !localError;

  if (hidden) return null;

  return (
    <Card
      title={presentation === "default" ? "人工确认" : undefined}
      icon={presentation === "default" ? <ShieldQuestion size={18} /> : undefined}
      className={presentation === "publication" ? "action-center-card--publication" : undefined}
      actions={
        showDiagnostic ? (
          <Button
            size="sm"
            variant="secondary"
            loading={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            <Play size={15} aria-hidden="true" />
            运行确认测试
          </Button>
        ) : undefined
      }
    >
      <div className="action-center" aria-live="polite">
        {actionsQuery.isLoading ? <p className="status-note">正在读取待确认动作…</p> : null}
        {!actionsQuery.isLoading && waitingForAction ? (
          <p className="status-note">正在等待待确认动作…</p>
        ) : null}
        {!actionsQuery.isLoading && actions.length === 0 && !waitingForAction ? (
          <p className="status-note">暂无待确认动作</p>
        ) : null}

        {actions.length > 1 ? (
          <div className="action-center__list" role="list" aria-label="待确认动作">
            {actions.map((item) => (
              <button
                key={item.id}
                type="button"
                className="action-center__list-item"
                aria-current={selected?.id === item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <span>{displayValue(item.preview.summary ?? item.actionType)}</span>
                <Badge tone="warning">待确认</Badge>
              </button>
            ))}
          </div>
        ) : null}

        {selected && presentation === "publication" ? (
          <div className="action-center__publication">
            <div className="action-center__publication-status">
              <Badge tone="warning" dot>等待你的决定</Badge>
              <span>批准后，这道题会进入可复习题库</span>
            </div>
            <section className="action-center__publication-preview" aria-label="待发布题目预览">
              <div><span>题目</span><strong>{editValue(selected, "title", edits) || "未命名题目"}</strong></div>
              <MarkdownView markdown={editValue(selected, "markdown", edits)} />
            </section>
            {selected.editableFields.length > 0 ? (
              <details className="action-center__publication-edit">
                <summary><PencilLine size={15} />调整标题或内容</summary>
                <div>
                  {selected.editableFields.includes("title") ? <Field label="题目标题" name={`action-${selected.id}-title`} value={editValue(selected, "title", edits)} onChange={(event) => setEdits((current) => ({ ...current, title: event.target.value }))} /> : null}
                  {selected.editableFields.includes("markdown") ? <label className="field" htmlFor={`action-${selected.id}-markdown`}><span className="field__label">Markdown 内容</span><textarea id={`action-${selected.id}-markdown`} className="field__input action-center__publication-markdown" value={editValue(selected, "markdown", edits)} onChange={(event) => setEdits((current) => ({ ...current, markdown: event.target.value }))} /></label> : null}
                </div>
              </details>
            ) : null}
            {showRejectReason ? <section className="action-center__reject-panel" aria-label="暂不发布原因"><label className="field" htmlFor={`action-${selected.id}-reason`}><span className="field__label">暂不发布原因</span><textarea id={`action-${selected.id}-reason`} className="field__input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明需要继续修改的地方" autoFocus /></label><div><Button variant="ghost" disabled={resolving} onClick={() => { setReason(""); setShowRejectReason(false); }}>返回</Button><Button variant="danger" disabled={!reason.trim() || resolving} loading={rejectMutation.isPending} onClick={() => rejectMutation.mutate(selected)}><X size={16} aria-hidden="true" />确认暂不发布</Button></div></section> : null}
            {!showRejectReason ? <footer className="action-center__publication-actions"><Button variant="ghost" disabled={resolving} onClick={() => setShowRejectReason(true)}>暂不发布</Button><Button loading={approveMutation.isPending} disabled={resolving} onClick={() => approveMutation.mutate(selected)}><Check size={16} aria-hidden="true" />批准并入库</Button></footer> : null}
          </div>
        ) : selected ? (
          <div className="action-center__detail">
            <div className="action-center__meta">
              <Badge tone="warning" dot>等待人工决定</Badge>
              <span>{selected.actionType}</span>
            </div>
            <dl className="action-center__preview">
              {Object.entries(selected.preview).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{displayValue(value)}</dd>
                </div>
              ))}
            </dl>
            {selected.editableFields.map((field) => (
              <Field
                key={field}
                label={field}
                name={`action-${selected.id}-${field}`}
                value={edits[field] ?? ""}
                onChange={(event) =>
                  setEdits((current) => ({ ...current, [field]: event.target.value }))
                }
              />
            ))}
            <Field
              label="拒绝原因"
              name={`action-${selected.id}-reason`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <div className="btn-row">
              <Button
                onClick={() => approveMutation.mutate(selected)}
                loading={approveMutation.isPending}
                disabled={resolving}
              >
                <Check size={16} aria-hidden="true" />
                批准
              </Button>
              <Button
                variant="danger"
                onClick={() => rejectMutation.mutate(selected)}
                loading={rejectMutation.isPending}
                disabled={resolving}
              >
                <X size={16} aria-hidden="true" />
                拒绝
              </Button>
            </div>
          </div>
        ) : null}

        {message ? <p className="status-note">{message}</p> : null}
        {localError ? (
          <div className="action-center__error" role="alert">
            <p className="status-note status-note--warning">{localError}</p>
            {watchExecutionId ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setLocalError(null);
                  setWatchAttempt((current) => current + 1);
                }}
              >
                重新检查
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
