import { FolderCog, LayoutDashboard, ServerCog, ShieldCheck } from "lucide-react";
import { Button } from "../../shared/ui/Button";

export type SettingsSection = "overview" | "workspace" | "models" | "diagnostics";

interface SettingsNavigationProps {
  current: SettingsSection;
  onSelect: (section: SettingsSection) => void;
  disabledSections?: readonly SettingsSection[];
}

const ITEMS: ReadonlyArray<{
  section: SettingsSection;
  label: string;
  description: string;
  icon: typeof LayoutDashboard;
}> = [
  { section: "overview", label: "配置概览", description: "查看当前状态", icon: LayoutDashboard },
  { section: "workspace", label: "工作区", description: "切换与数据管理", icon: FolderCog },
  { section: "models", label: "模型服务", description: "服务与任务分配", icon: ServerCog },
  { section: "diagnostics", label: "运行诊断", description: "Runtime 与安全检查", icon: ShieldCheck },
];

export function SettingsNavigation({
  current,
  onSelect,
  disabledSections = [],
}: SettingsNavigationProps) {
  return (
    <nav className="settings-navigation" aria-label="设置分组">
      <p className="settings-navigation__eyebrow">设置分组</p>
      <div className="settings-nav__list">
        {ITEMS.map(({ section, label, description, icon: Icon }) => {
          const disabled = disabledSections.includes(section);
          return (
            <Button
              key={section}
              variant="ghost"
              className="settings-nav__item"
              aria-label={label}
              aria-current={current === section ? "page" : undefined}
              disabled={disabled}
              onClick={() => onSelect(section)}
            >
              <Icon size={18} aria-hidden="true" />
              <span className="settings-nav__copy">
                <span className="settings-nav__label">{label}</span>
                <span className="settings-nav__description">{description}</span>
              </span>
            </Button>
          );
        })}
      </div>
    </nav>
  );
}
