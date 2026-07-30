import { Archive, BriefcaseBusiness, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { JobTarget } from "./jobTargetTypes";

interface JobTargetListProps {
  targets: JobTarget[];
  selectedId?: string | null;
  collapsed?: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onToggleCollapsed?: () => void;
}

export function JobTargetList({
  targets,
  selectedId,
  collapsed = false,
  onSelect,
  onCreate,
  onToggleCollapsed,
}: JobTargetListProps) {
  return <aside className="job-target-list" data-collapsed={collapsed}>
    <header>
      <div>
        <h2>求职目标</h2>
        <p>{targets.length} 个目标</p>
      </div>
      <div className="job-target-list__actions">
        <Button className="job-target-list__create" variant="secondary" aria-label="新建求职目标" onClick={onCreate}><Plus size={17} /></Button>
        {onToggleCollapsed ? <Button className="job-target-list__collapse" variant="ghost" aria-label={collapsed ? "展开求职目标列表" : "收起求职目标列表"} aria-expanded={!collapsed} onClick={onToggleCollapsed}>
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </Button> : null}
      </div>
    </header>
    <label className="job-target-list__mobile-picker">
      <span>当前目标</span>
      <SelectControl aria-label="当前求职目标" value={selectedId ?? targets[0]?.id ?? ""} onChange={(event) => onSelect(event.target.value)}>
        {targets.map((target) => <option key={target.id} value={target.id}>{target.roleName || "岗位信息待补充"}{target.companyName ? ` · ${target.companyName}` : ""}</option>)}
      </SelectControl>
    </label>
    <div>
      {targets.map((target) => {
        const title = target.roleName || "岗位信息待补充";
        const subtitle = [target.companyName, target.seniority].filter(Boolean).join(" · ") || "已保存岗位描述";
        return <button key={target.id} type="button" className={selectedId === target.id ? "is-active" : ""} aria-label={`${title} ${subtitle}`} title={collapsed ? `${title} · ${subtitle}` : undefined} onClick={() => onSelect(target.id)}>
          <BriefcaseBusiness size={18} />
          <span><strong>{title}</strong><small>{subtitle}</small></span>
          {target.lifecycleStatus === "archived" ? <Archive className="job-target-list__archived" size={15} aria-label="已归档" /> : null}
        </button>;
      })}
    </div>
  </aside>;
}
