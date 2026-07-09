import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
}

export function Button({ children, type = "button", ...props }: ButtonProps) {
  return <button type={type} {...props}>{children}</button>;
}
