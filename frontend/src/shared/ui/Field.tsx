import type { InputHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  helper?: ReactNode;
  error?: string;
}

export function Field({ label, id, name, helper, error, className, ...props }: FieldProps) {
  const inputId = id ?? name ?? label;
  return (
    <div className={clsx("field", error && "field--error", className)}>
      <label className="field__label" htmlFor={inputId}>
        {label}
      </label>
      <input id={inputId} name={name} className="field__input" {...props} />
      {helper ? <p className="field__helper">{helper}</p> : null}
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
