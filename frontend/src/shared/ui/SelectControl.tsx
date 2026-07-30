import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import {
  forwardRef,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";


interface SelectControlProps extends SelectHTMLAttributes<HTMLSelectElement> {
  containerClassName?: string;
  controlSize?: "sm" | "md";
  icon?: ReactNode;
  label?: ReactNode;
}

export const SelectControl = forwardRef<HTMLSelectElement, SelectControlProps>(
  function SelectControl(
    {
      children,
      className,
      containerClassName,
      controlSize = "md",
      disabled,
      icon,
      label,
      ...props
    },
    ref,
  ) {
    return (
      <span
        className={clsx("select-control", containerClassName)}
        data-disabled={disabled ? "true" : "false"}
        data-has-icon={icon ? "true" : "false"}
        data-layout={label ? "stacked" : "single"}
        data-size={controlSize}
      >
        {icon ? (
          <span className="select-control__icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        {label ? (
          <span className="select-control__label" aria-hidden="true">
            {label}
          </span>
        ) : null}
        <select
          ref={ref}
          className={clsx("select-control__input", className)}
          disabled={disabled}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          className="select-control__chevron"
          size={16}
          aria-hidden="true"
        />
      </span>
    );
  },
);
