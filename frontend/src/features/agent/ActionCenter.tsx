import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Play, ShieldQuestion, X } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { Field } from "../../shared/ui/Field";
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
}

export function ActionCenter({
  workspaceId,
  showDiagnostic = true,
  actionType,
  watchExecutionId,
  onResolved,
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
  const [watchAttempt, setWatchAttempt] = useState(0);
  const operationKeys = useRef(new Map<string, string>());

  const actionsQuery = useQuery({
    queryKey,
    queryFn: () => listActions(workspaceId, { status: "pending" }),
  });
  const allActions = actionsQuery.data ?? [];
  const actions = actionType
    ? allActions.filter((item) => item.actionType === actionType)
    : allActions;
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
          .filter((field) => edits[field] !== displayValue(action.preview[field] ?? ""))
          .map((field) => [field, edits[field]]),
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
      title="人工确认"
      icon={<ShieldQuestion size={18} />}
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

        {selected ? (
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
