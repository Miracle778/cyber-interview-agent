import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";

export interface ProjectOption { id: string; title: string; summary?: string }

export function ProjectPriorityPanel({
  projects,
  initialCoreProjectId,
  initialSupplementaryProjectIds = [],
  saving,
  startingProjectId,
  saveError,
  onSave,
  onStart,
}: {
  projects: ProjectOption[];
  initialCoreProjectId?: string | null;
  initialSupplementaryProjectIds?: string[];
  saving?: boolean;
  startingProjectId?: string | null;
  saveError?: string | null;
  onSave: (core: string, supplementary: string[]) => void;
  onStart: (projectId: string) => void;
}) {
  const defaultCore = initialCoreProjectId ?? projects[0]?.id ?? "";
  const [core, setCore] = useState(defaultCore);
  const [supplementary, setSupplementary] = useState<string[]>(initialSupplementaryProjectIds);
  useEffect(() => {
    setCore(initialCoreProjectId ?? projects[0]?.id ?? "");
    setSupplementary(initialSupplementaryProjectIds);
  }, [initialCoreProjectId, initialSupplementaryProjectIds.join("|"), projects[0]?.id]);
  const changed = useMemo(
    () => core !== (initialCoreProjectId ?? "") ||
      [...supplementary].sort().join("|") !== [...initialSupplementaryProjectIds].sort().join("|"),
    [core, initialCoreProjectId, initialSupplementaryProjectIds, supplementary],
  );
  return <section className="project-priority-panel"><header><h2>重点准备项目</h2><p>选 1 个核心项目、最多 2 个补充项目。项目本身仍归个人画像管理。</p></header>
    <div>{projects.map((project) => <article key={project.id}><div><strong>{project.title}</strong><p>{project.summary || "已确认的个人项目"}</p></div><label><input aria-label={`设为核心项目：${project.title}`} type="radio" name="core-project" checked={core === project.id} onChange={() => { setCore(project.id); setSupplementary((ids) => ids.filter((id) => id !== project.id)); }} />核心项目</label><label><input aria-label={`设为补充项目：${project.title}`} type="checkbox" disabled={core === project.id || (!supplementary.includes(project.id) && supplementary.length >= 2)} checked={supplementary.includes(project.id)} onChange={() => setSupplementary((ids) => ids.includes(project.id) ? ids.filter((id) => id !== project.id) : [...ids, project.id])} />补充项目</label><Button variant="secondary" loading={startingProjectId === project.id} disabled={Boolean(startingProjectId)} onClick={() => onStart(project.id)}>开始深挖</Button></article>)}</div>
    <footer><div><span>{core ? "已选择核心项目" : "请选择核心项目"} · {supplementary.length}/2 个补充项目</span>{saveError ? <p role="alert">保存失败：{saveError}</p> : !changed && initialCoreProjectId ? <p role="status">项目重点已保存</p> : changed ? <p>选择有变更，保存后会用于准备总览和项目深挖。</p> : null}</div><Button disabled={!core || !changed || saving} loading={saving} onClick={() => onSave(core, supplementary)}>{changed ? "保存项目重点" : "已保存"}</Button></footer>
  </section>;
}
