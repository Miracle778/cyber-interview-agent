import {
  Activity,
  Bot,
  Box,
  BrainCircuit,
  ChevronRight,
  GitBranch,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatDuration, statusLabel } from "./ExecutionList";
import {
  friendlyEventName,
  friendlyOperationName,
  executionStartPresentation,
  failureEventWasRecovered,
  isFailureEventType,
  operationWasRecovered,
  operationStatusLabel,
} from "./observabilityLabels";
import type { OperationSummary, TraceEventSummary } from "./observabilityTypes";


interface OperationTreeProps {
  operations: OperationSummary[];
  events?: TraceEventSummary[];
  selectedId: string | null;
  selectedEventId?: string | null;
  executionStatus?: string;
  onSelect: (operationId: string) => void;
  onSelectEvent?: (eventId: string) => void;
}

function OperationIcon({ kind }: { kind: OperationSummary["kind"] }) {
  if (kind === "agent") return <Bot size={16} aria-hidden="true" />;
  if (kind === "model") return <BrainCircuit size={16} aria-hidden="true" />;
  if (kind === "tool") return <Box size={16} aria-hidden="true" />;
  if (kind === "graph") return <GitBranch size={16} aria-hidden="true" />;
  return <Workflow size={16} aria-hidden="true" />;
}

export function OperationTree({
  operations,
  events = [],
  selectedId,
  selectedEventId = null,
  executionStatus,
  onSelect,
  onSelectEvent,
}: OperationTreeProps) {
  const { childrenByParent, roots } = useMemo(() => {
    const ids = new Set(operations.map((operation) => operation.id));
    const children = new Map<string, OperationSummary[]>();
    const rootItems: OperationSummary[] = [];
    for (const operation of operations) {
      if (!operation.parentOperationId || !ids.has(operation.parentOperationId)) {
        rootItems.push(operation);
        continue;
      }
      children.set(operation.parentOperationId, [
        ...(children.get(operation.parentOperationId) ?? []),
        operation,
      ]);
    }
    return { childrenByParent: children, roots: rootItems };
  }, [operations]);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const eventsByOperation = useMemo(() => {
    const groups = new Map<string, TraceEventSummary[]>();
    for (const event of events) {
      groups.set(event.operationId, [
        ...(groups.get(event.operationId) ?? []),
        event,
      ]);
    }
    return groups;
  }, [events]);
  const { displayRoots, promotedRoots, firstSequenceByOperation } = useMemo(() => {
    const sequenceCache = new Map<string, number>();

    function firstSequence(operationId: string, visiting = new Set<string>()): number {
      const cached = sequenceCache.get(operationId);
      if (cached !== undefined) return cached;
      if (visiting.has(operationId)) return Number.POSITIVE_INFINITY;
      const nextVisiting = new Set(visiting).add(operationId);
      const directSequences = (eventsByOperation.get(operationId) ?? [])
        .map((event) => event.sequence);
      const childSequences = (childrenByParent.get(operationId) ?? [])
        .map((child) => firstSequence(child.id, nextVisiting));
      const sequence = Math.min(
        ...directSequences,
        ...childSequences,
        Number.POSITIVE_INFINITY,
      );
      sequenceCache.set(operationId, sequence);
      return sequence;
    }

    for (const operation of operations) firstSequence(operation.id);
    const namedWrapperRoots = roots.filter((operation) =>
      operation.name.trim().toLocaleLowerCase() === "execution_runtime");
    const idWrapperRoots = roots.filter((operation) =>
      operation.id === `execution:${operation.runId}`);
    const executionRoots = roots.filter((operation) => operation.kind === "execution");
    const executionRoot = namedWrapperRoots.length === 1
      ? namedWrapperRoots[0]
      : idWrapperRoots.length === 1
        ? idWrapperRoots[0]
        : executionRoots.length === 1
          ? executionRoots[0]
          : null;
    return {
      displayRoots: executionRoot ? [executionRoot] : roots,
      promotedRoots: executionRoot
        ? roots.filter((operation) => operation.id !== executionRoot.id)
        : [],
      firstSequenceByOperation: sequenceCache,
    };
  }, [childrenByParent, eventsByOperation, operations, roots]);

  function moveFocus(target: EventTarget & HTMLElement, direction: -1 | 1) {
    const items = [...target.closest('[role="tree"]')!.querySelectorAll<HTMLElement>('[role="treeitem"]')];
    const index = items.indexOf(target);
    items[index + direction]?.focus();
  }

  function renderOperation(operation: OperationSummary, level: number) {
    const children = [
      ...(childrenByParent.get(operation.id) ?? []),
      ...(displayRoots[0]?.id === operation.id ? promotedRoots : []),
    ];
    const operationEvents = (eventsByOperation.get(operation.id) ?? []).filter(
      (event) => event.eventType !== "execution.started"
        || executionStartPresentation(event, events) !== null,
    );
    const hasChildren = children.length > 0 || operationEvents.length > 0;
    const expanded = hasChildren && !collapsedIds.has(operation.id);
    const recovered = operationWasRecovered(operation, events, operations);
    const timelineItems = [
      ...children.map((child, index) => ({
        kind: "operation" as const,
        operation: child,
        sequence: firstSequenceByOperation.get(child.id) ?? Number.POSITIVE_INFINITY,
        timestamp: child.startedAt ? Date.parse(child.startedAt) : Number.POSITIVE_INFINITY,
        index,
      })),
      ...operationEvents.map((event, index) => ({
        kind: "event" as const,
        event,
        sequence: event.sequence,
        timestamp: event.observedAt ? Date.parse(event.observedAt) : Number.POSITIVE_INFINITY,
        index: children.length + index,
      })),
    ].sort((left, right) => {
      if (left.sequence !== right.sequence) return left.sequence - right.sequence;
      if (left.timestamp !== right.timestamp) return left.timestamp - right.timestamp;
      if (left.kind !== right.kind) return left.kind === "operation" ? -1 : 1;
      return left.index - right.index;
    });
    return (
      <li role="none" key={operation.id}>
        <button
          type="button"
          role="treeitem"
          aria-level={level}
          aria-selected={selectedId === operation.id}
          aria-expanded={hasChildren ? expanded : undefined}
          className="operation-tree__item"
          onClick={() => onSelect(operation.id)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              moveFocus(event.currentTarget, event.key === "ArrowDown" ? 1 : -1);
            } else if (event.key === "ArrowRight" && hasChildren) {
              setCollapsedIds((current) => {
                const next = new Set(current);
                next.delete(operation.id);
                return next;
              });
            } else if (event.key === "ArrowLeft" && hasChildren) {
              setCollapsedIds((current) => new Set(current).add(operation.id));
            }
          }}
        >
          <span
            className="operation-tree__chevron"
            data-visible={hasChildren}
            data-expanded={expanded}
            aria-hidden="true"
            onClick={(event) => {
              if (!hasChildren) return;
              event.stopPropagation();
              setCollapsedIds((current) => {
                const next = new Set(current);
                if (next.has(operation.id)) next.delete(operation.id);
                else next.add(operation.id);
                return next;
              });
            }}
          >
            <ChevronRight size={15} />
          </span>
          <span className="operation-tree__icon" data-kind={operation.kind}>
            <OperationIcon kind={operation.kind} />
          </span>
          <span className="operation-tree__copy">
            <strong title={operation.name}>{friendlyOperationName(operation)}</strong>
            <small>
              {operationStatusLabel(operation.status, executionStatus, recovered)
                ?? statusLabel(operation.status)}
              {" · "}
              {formatDuration(operation.latencyMs)}
            </small>
          </span>
        </button>
        {expanded ? (
          <ul role="group">
            {timelineItems.map((item) => {
              if (item.kind === "operation") {
                return renderOperation(item.operation, level + 1);
              }
              const recoveredFailure = failureEventWasRecovered(item.event, events);
              const startPresentation = executionStartPresentation(item.event, events);
              return (
              <li role="none" key={item.event.eventId}>
                <button
                  type="button"
                  role="treeitem"
                  aria-level={level + 1}
                  aria-selected={selectedEventId === item.event.eventId}
                  data-tone={
                    recoveredFailure
                      ? "recovered"
                      : isFailureEventType(item.event.eventType)
                        ? "danger"
                        : undefined
                  }
                  className="operation-tree__item operation-tree__event"
                  onClick={() => onSelectEvent?.(item.event.eventId)}
                  onKeyDown={(keyboardEvent) => {
                    if (keyboardEvent.key === "ArrowDown" || keyboardEvent.key === "ArrowUp") {
                      keyboardEvent.preventDefault();
                      moveFocus(
                        keyboardEvent.currentTarget,
                        keyboardEvent.key === "ArrowDown" ? 1 : -1,
                      );
                    }
                  }}
                >
                  <span className="operation-tree__chevron" data-visible="false" />
                  <span className="operation-tree__icon" data-kind="event">
                    <Activity size={15} aria-hidden="true" />
                  </span>
                  <span className="operation-tree__copy">
                    <strong title={item.event.eventType}>
                      {friendlyEventName(
                        item.event.eventType,
                        recoveredFailure,
                        startPresentation === "recovery",
                      )}
                    </strong>
                    <small>
                      事件 #{item.event.sequence} · {item.event.byteLength.toLocaleString()} B
                    </small>
                  </span>
                </button>
              </li>
              );
            })}
          </ul>
        ) : null}
      </li>
    );
  }

  return (
    <div className="operation-tree" role="tree" aria-label="执行过程">
      <ul role="none">
        {displayRoots.map((operation) => renderOperation(operation, 1))}
      </ul>
    </div>
  );
}
