import { AlertTriangle, CheckCircle2, CircleHelp, FolderCog, ServerCog, ShieldCheck, Workflow } from "lucide-react";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import type { SettingsSection } from "./SettingsNavigation";

export type SettingsStatusTone = "neutral" | "success" | "warning" | "danger";

export interface SettingsStatusItem {
  id: "workspace" | "providers" | "bindings" | "diagnostics";
  title: string;
  status: string;
  description: string;
  tone: SettingsStatusTone;
  section: Exclude<SettingsSection, "overview">;
}

interface SettingsOverviewProps {
  items: readonly SettingsStatusItem[];
  recommendedSection: Exclude<SettingsSection, "overview">;
  onSelect: (section: SettingsSection) => void;
}

const ICONS = {
  workspace: FolderCog,
  providers: ServerCog,
  bindings: Workflow,
  diagnostics: ShieldCheck,
} as const;

const NEXT_ACTIONS: Record<SettingsOverviewProps["recommendedSection"], string> = {
  workspace: "下一步：初始化工作区",
  models: "下一步：配置模型服务",
  diagnostics: "下一步：运行诊断",
};

export function SettingsOverview({ items, recommendedSection, onSelect }: SettingsOverviewProps) {
  return (
    <section className="settings-overview" aria-labelledby="settings-overview-title">
      <div className="settings-content__header">
        <div>
          <p className="settings-content__eyebrow">配置进度</p>
          <h3 id="settings-overview-title">配置概览</h3>
          <p className="settings-content__description">按顺序完成工作区、模型服务和运行检查。</p>
        </div>
        <CircleHelp size={20} aria-hidden="true" className="settings-overview__help" />
      </div>

      <div className="settings-overview__list">
        {items.map((item) => {
          const Icon = ICONS[item.id];
          const StatusIcon = item.tone === "success"
            ? CheckCircle2
            : item.tone === "danger" || item.tone === "warning"
              ? AlertTriangle
              : CircleHelp;
          return (
            <article className="settings-overview__item" key={item.id}>
              <span className="settings-overview__icon" aria-hidden="true"><Icon size={19} /></span>
              <div className="settings-overview__body">
                <div className="settings-overview__title-row">
                  <h4>{item.title}</h4>
                  <Badge tone={item.tone} dot>
                    <StatusIcon size={13} aria-hidden="true" />
                    {item.status}
                  </Badge>
                </div>
                <p>{item.description}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onSelect(item.section)}
                aria-label={`查看${item.title}`}
              >
                查看
              </Button>
            </article>
          );
        })}
      </div>

      <div className="settings-overview__next">
        <div>
          <p className="settings-overview__next-label">推荐下一步</p>
          <p className="settings-overview__next-copy">先完成当前阻塞项，后续诊断才有可靠结果。</p>
        </div>
        <Button onClick={() => onSelect(recommendedSection)}>
          {NEXT_ACTIONS[recommendedSection]}
        </Button>
      </div>
    </section>
  );
}
