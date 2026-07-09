import { Loader2 } from "lucide-react";

interface SpinnerProps {
  size?: number;
  className?: string;
}

/** Decorative loading spinner. Always aria-hidden. */
export function Spinner({ size = 16, className }: SpinnerProps) {
  return <Loader2 size={size} className={className} aria-hidden="true" />;
}
