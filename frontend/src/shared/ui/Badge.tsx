import type { ReactNode } from "react";
import clsx from "clsx";

type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
}

export function Badge({ children, tone = "neutral", dot = false, className }: BadgeProps) {
  return (
    <span className={clsx("badge", `badge--${tone}`, className)}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
