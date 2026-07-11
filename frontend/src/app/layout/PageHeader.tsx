import { AlertTriangle, CheckCircle2, Folder, Loader2 } from "lucide-react";
import type { WorkspaceConfig } from "../../features/settings/settingsApi";

type HealthStatus = "checking" | "connected" | "disconnected";

interface PageHeaderProps {
  title: string;
  description: string;
  healthStatus: HealthStatus;
  healthMessage: string;
  workspace: WorkspaceConfig | null;
}

export function PageHeader({
  title,
  description,
  healthStatus,
  healthMessage,
  workspace,
}: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="page-header__status" aria-label="运行状态">
        <span className="status-chip" data-state={healthStatus} title={healthMessage}>
          {healthStatus === "connected" ? (
            <CheckCircle2 size={15} aria-hidden="true" />
          ) : healthStatus === "disconnected" ? (
            <AlertTriangle size={15} aria-hidden="true" />
          ) : (
            <Loader2 size={15} className="status-chip__spin" aria-hidden="true" />
          )}
          {healthMessage}
        </span>
        <span className="status-chip" data-state={workspace ? "connected" : "neutral"}>
          <Folder size={15} aria-hidden="true" />
          {workspace ? `Workspace：${workspace.workspacePath}` : "Workspace：待初始化"}
        </span>
      </div>
    </header>
  );
}
