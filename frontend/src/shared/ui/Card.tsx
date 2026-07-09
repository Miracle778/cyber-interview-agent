import type { ReactNode } from "react";
import clsx from "clsx";

interface CardProps {
  title?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  ariaLabel?: string;
}

export function Card({ title, icon, actions, children, className, bodyClassName, ariaLabel }: CardProps) {
  return (
    <div className={clsx("card", className)} aria-label={ariaLabel}>
      {title || actions ? (
        <header className="card__header">
          <div className="card__title">
            {icon ? (
              <span className="card__icon" aria-hidden="true">
                {icon}
              </span>
            ) : null}
            {title ? <h3 className="card__heading">{title}</h3> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={clsx("card__body", bodyClassName)}>{children}</div>
    </div>
  );
}
