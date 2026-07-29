import {
  Bot,
  Box,
  BrainCircuit,
  ChevronRight,
  GitBranch,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatDuration, statusLabel } from "./ExecutionList";
import type { OperationSummary } from "./observabilityTypes";


interface OperationTreeProps {
  operations: OperationSummary[];
  selectedId: string | null;
  onSelect: (operationId: string) => void;
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
  selectedId,
  onSelect,
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

  function moveFocus(target: EventTarget & HTMLElement, direction: -1 | 1) {
    const items = [...target.closest('[role="tree"]')!.querySelectorAll<HTMLElement>('[role="treeitem"]')];
    const index = items.indexOf(target);
    items[index + direction]?.focus();
  }

  function renderOperation(operation: OperationSummary, level: number) {
    const children = childrenByParent.get(operation.id) ?? [];
    const expanded = children.length > 0 && !collapsedIds.has(operation.id);
    return (
      <li role="none" key={operation.id}>
        <button
          type="button"
          role="treeitem"
          aria-level={level}
          aria-selected={selectedId === operation.id}
          aria-expanded={children.length > 0 ? expanded : undefined}
          className="operation-tree__item"
          onClick={() => onSelect(operation.id)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              moveFocus(event.currentTarget, event.key === "ArrowDown" ? 1 : -1);
            } else if (event.key === "ArrowRight" && children.length > 0) {
              setCollapsedIds((current) => {
                const next = new Set(current);
                next.delete(operation.id);
                return next;
              });
            } else if (event.key === "ArrowLeft" && children.length > 0) {
              setCollapsedIds((current) => new Set(current).add(operation.id));
            }
          }}
        >
          <span
            className="operation-tree__chevron"
            data-visible={children.length > 0}
            data-expanded={expanded}
            aria-hidden="true"
            onClick={(event) => {
              if (children.length === 0) return;
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
            <strong>{operation.name}</strong>
            <small>
              {statusLabel(operation.status)} · {formatDuration(operation.latencyMs)}
            </small>
          </span>
        </button>
        {expanded ? (
          <ul role="group">
            {children.map((child) => renderOperation(child, level + 1))}
          </ul>
        ) : null}
      </li>
    );
  }

  return (
    <div className="operation-tree" role="tree" aria-label="执行过程">
      <ul role="none">
        {roots.map((operation) => renderOperation(operation, 1))}
      </ul>
    </div>
  );
}
