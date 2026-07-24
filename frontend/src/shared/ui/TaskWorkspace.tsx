import type { HTMLAttributes, ReactNode } from "react";

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function TaskWorkspace({
  children,
  className,
  labelledBy,
}: {
  children: ReactNode;
  className?: string;
  labelledBy?: string;
}) {
  return <section className={classNames("task-workspace", className)} aria-labelledby={labelledBy}>{children}</section>;
}

export function TaskWorkspacePane({
  children,
  className,
  scroll = true,
  ...props
}: HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  scroll?: boolean;
}) {
  return <section className={classNames("task-workspace__pane", scroll && "task-workspace__pane--scroll", className)} {...props}>{children}</section>;
}
