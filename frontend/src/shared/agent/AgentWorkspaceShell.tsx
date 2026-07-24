import type { ReactNode } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

interface AgentWorkspaceShellProps {
  header: ReactNode;
  conversation: ReactNode;
  aside: ReactNode;
  asideOpen: boolean;
  onAsideOpenChange: (open: boolean) => void;
  asideLabel?: string;
}

export function AgentWorkspaceShell({
  header,
  conversation,
  aside,
  asideOpen,
  onAsideOpenChange,
  asideLabel = "本次依据",
}: AgentWorkspaceShellProps) {
  return (
    <section className={`agent-workspace${asideOpen ? "" : " agent-workspace--aside-collapsed"}`}>
      <header className="agent-workspace__header">
        <div>{header}</div>
        <button
          type="button"
          className="agent-workspace__aside-toggle"
          aria-expanded={asideOpen}
          aria-controls="agent-workspace-aside"
          onClick={() => onAsideOpenChange(!asideOpen)}
        >
          {asideOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          <span>{asideOpen ? "收起依据" : asideLabel}</span>
        </button>
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
