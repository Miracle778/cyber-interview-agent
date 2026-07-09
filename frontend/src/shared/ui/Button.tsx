import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";
import { Spinner } from "./Spinner";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export function Button({
  children,
  type = "button",
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={clsx("btn", `btn--${variant}`, `btn--${size}`, loading && "btn--loading", className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Spinner size={size === "sm" ? 14 : 16} className="btn__spinner" /> : null}
      <span className="btn__label">{children}</span>
    </button>
  );
}
