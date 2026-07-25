import { Archive, BriefcaseBusiness, Plus } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { JobTarget } from "./jobTargetTypes";

export function JobTargetList({ targets, selectedId, onSelect, onCreate }: { targets: JobTarget[]; selectedId?: string | null; onSelect: (id: string) => void; onCreate: () => void }) {
  return <aside className="job-target-list"><header><div><h2>求职目标</h2><p>{targets.length} 个目标</p></div><Button variant="secondary" aria-label="新建求职目标" onClick={onCreate}><Plus size={17} /></Button></header><label className="job-target-list__mobile-picker"><span>当前目标</span><select aria-label="当前求职目标" value={selectedId ?? targets[0]?.id ?? ""} onChange={(event) => onSelect(event.target.value)}>{targets.map((target) => <option key={target.id} value={target.id}>{target.roleName || "岗位信息待补充"}{target.companyName ? ` · ${target.companyName}` : ""}</option>)}</select></label><div>{targets.map((target) => <button key={target.id} type="button" className={selectedId === target.id ? "is-active" : ""} onClick={() => onSelect(target.id)}><BriefcaseBusiness size={18} /><span><strong>{target.roleName || "岗位信息识别中"}</strong><small>{[target.companyName, target.seniority].filter(Boolean).join(" · ") || "已保存岗位描述"}</small></span>{target.lifecycleStatus === "archived" ? <Archive size={15} aria-label="已归档" /> : null}</button>)}</div></aside>;
}
