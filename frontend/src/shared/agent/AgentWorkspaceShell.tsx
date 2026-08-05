import { useEffect, type ReactNode } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

interface AgentWorkspaceShellProps {
  header: ReactNode;
  conversation: ReactNode;
  aside: ReactNode;
  asideOpen: boolean;
  onAsideOpenChange: (open: boolean) => void;
  asideLabel?: string;
  headerTrailing?: ReactNode;
}

export function AgentWorkspaceShell({
  header,
  conversation,
  aside,
  asideOpen,
  onAsideOpenChange,
  asideLabel = "本次依据",
  headerTrailing,
}: AgentWorkspaceShellProps) {
  useEffect(() => {
    const compact = globalThis.matchMedia?.("(max-width: 1199px)");
    if (!compact) return;
    const closeCompactAside = (event?: MediaQueryListEvent) => {
      if (event?.matches ?? compact.matches) onAsideOpenChange(false);
    };
    closeCompactAside();
    compact.addEventListener?.("change", closeCompactAside);
    return () => compact.removeEventListener?.("change", closeCompactAside);
  }, [onAsideOpenChange]);

  return (
    <section className={`agent-workspace${asideOpen ? "" : " agent-workspace--aside-collapsed"}`}>
      <header className="agent-workspace__header">
        <div>{header}</div>
        <button
          type="button"
          className="agent-workspace__aside-toggle"
          aria-label={asideOpen ? `收起${asideLabel}` : `打开${asideLabel}`}
          aria-expanded={asideOpen}
          aria-controls="agent-workspace-aside"
          onClick={() => onAsideOpenChange(!asideOpen)}
        >
          {asideOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          <span>{asideOpen ? "收起依据" : asideLabel}</span>
        </button>
        {headerTrailing}
      </header>
      <div className="agent-workspace__body">
        <div className="agent-workspace__conversation">{conversation}</div>
        <aside id="agent-workspace-aside" className="agent-workspace__aside" aria-label={asideLabel}>
          {aside}
        </aside>
      </div>
    </section>
  );
}
