import { useState } from "react";
import { Button } from "../../shared/ui/Button";

export interface ProjectOption { id: string; title: string; summary?: string }

export function ProjectPriorityPanel({ projects, busy, onSave, onStart }: { projects: ProjectOption[]; busy?: boolean; onSave: (core: string, supplementary: string[]) => void; onStart: (projectId: string) => void }) {
  const [core, setCore] = useState(projects[0]?.id ?? "");
  const [supplementary, setSupplementary] = useState<string[]>([]);
  return <section className="project-priority-panel"><header><h2>重点准备项目</h2><p>选 1 个核心项目、最多 2 个补充项目。项目本身仍归个人画像管理。</p></header>
    <div>{projects.map((project) => <article key={project.id}><div><strong>{project.title}</strong><p>{project.summary || "已确认的个人项目"}</p></div><label><input type="radio" name="core-project" checked={core === project.id} onChange={() => { setCore(project.id); setSupplementary((ids) => ids.filter((id) => id !== project.id)); }} />核心项目</label><label><input type="checkbox" disabled={core === project.id || (!supplementary.includes(project.id) && supplementary.length >= 2)} checked={supplementary.includes(project.id)} onChange={() => setSupplementary((ids) => ids.includes(project.id) ? ids.filter((id) => id !== project.id) : [...ids, project.id])} />补充项目</label><Button variant="secondary" onClick={() => onStart(project.id)}>开始深挖</Button></article>)}</div>
    <footer><span>{core ? "已选择核心项目" : "请选择核心项目"} · {supplementary.length}/2 个补充项目</span><Button disabled={!core || busy} onClick={() => onSave(core, supplementary)}>保存项目重点</Button></footer>
  </section>;
}
