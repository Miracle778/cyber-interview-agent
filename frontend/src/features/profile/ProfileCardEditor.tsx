import { useMemo, useState } from "react";
import { AlertCircle, Trash2, X } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { ProfileCardCategory, ProfileCardCommand, UnifiedProfileCard } from "./profileTypes";

type FieldSpec = { key: string; label: string; required?: boolean; multiline?: boolean; list?: boolean; placeholder?: string; type?: "url" };

const categoryLabels: Record<ProfileCardCategory, string> = {
  summary: "个人简介",
  direction: "求职方向",
  highlight: "个人亮点",
  experience: "工作经历",
  project: "项目经历",
  skill: "技能",
  education: "教育经历",
  certification: "证书",
  achievement: "成果",
  link: "个人链接",
};

const fields: Record<ProfileCardCategory, FieldSpec[]> = {
  summary: [{ key: "text", label: "个人简介", required: true, multiline: true, placeholder: "用几句话介绍你的方向、经验和优势" }],
  direction: [{ key: "name", label: "方向名称", required: true, placeholder: "例如：后端开发工程师" }, { key: "description", label: "补充说明", multiline: true, placeholder: "你希望解决什么问题，或偏好的业务方向" }],
  highlight: [{ key: "text", label: "亮点", required: true, multiline: true, placeholder: "例如：能独立完成从需求拆解到上线的后端服务开发" }],
  experience: [
    { key: "organization", label: "公司或组织", required: true },
    { key: "title", label: "职位" },
    { key: "period", label: "时间" },
    { key: "location", label: "地点" },
    { key: "responsibilities", label: "主要工作", list: true, multiline: true, placeholder: "每行一项" },
    { key: "achievements", label: "成果", list: true, multiline: true, placeholder: "每行一项，尽量写清结果" },
  ],
  project: [
    { key: "name", label: "项目名称", required: true },
    { key: "period", label: "时间" },
    { key: "background", label: "项目背景", multiline: true, placeholder: "为什么要做这个项目" },
    { key: "role", label: "你的角色" },
    { key: "responsibilities", label: "负责内容", list: true, multiline: true, placeholder: "每行一项" },
    { key: "key_actions", label: "关键做法", list: true, multiline: true, placeholder: "每行一项，写清你具体做了什么" },
    { key: "tech_stack", label: "使用的技术", list: true, placeholder: "每行一个，例如 FastAPI" },
    { key: "results", label: "项目结果", list: true, multiline: true, placeholder: "每行一项，尽量包含可验证的结果" },
  ],
  skill: [{ key: "name", label: "技能名称", required: true }, { key: "self_assessment", label: "熟悉程度" }, { key: "notes", label: "补充说明", multiline: true }],
  education: [
    { key: "school", label: "学校", required: true },
    { key: "degree", label: "学历" },
    { key: "major", label: "专业" },
    { key: "period", label: "时间" },
    { key: "highlights", label: "相关课程或亮点", list: true, multiline: true, placeholder: "每行一项" },
  ],
  certification: [
    { key: "name", label: "证书名称", required: true },
    { key: "issuer", label: "颁发机构" },
    { key: "issued_at", label: "获得时间" },
    { key: "credential_id", label: "证书编号" },
    { key: "url", label: "验证链接", type: "url" },
  ],
  achievement: [{ key: "title", label: "成果名称", required: true }, { key: "description", label: "成果说明", multiline: true }, { key: "date", label: "时间" }],
  link: [{ key: "label", label: "链接名称", required: true, placeholder: "例如：GitHub" }, { key: "url", label: "网址", required: true, type: "url", placeholder: "https://..." }],
};

function initialDraft(card: UnifiedProfileCard | null, category: ProfileCardCategory) {
  return Object.fromEntries(fields[category].map((field) => {
    const value = card?.value[field.key];
    return [field.key, Array.isArray(value) ? value.join("\n") : typeof value === "string" ? value : ""];
  }));
}

export function ProfileCardEditor({
  card,
  initialCategory = "project",
  busy,
  error,
  onSave,
  onDelete,
  onCancel,
}: {
  card: UnifiedProfileCard | null;
  initialCategory?: ProfileCardCategory;
  busy: boolean;
  error: string | null;
  onSave: (command: Omit<ProfileCardCommand, "workspaceId">) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
  onCancel: () => void;
}) {
  const [category, setCategory] = useState<ProfileCardCategory>(card?.category ?? initialCategory);
  const [draft, setDraft] = useState<Record<string, string>>(() => initialDraft(card, card?.category ?? initialCategory));
  const [validation, setValidation] = useState<string | null>(null);
  const specs = useMemo(() => fields[category], [category]);

  function changeCategory(next: ProfileCardCategory) {
    setCategory(next);
    setDraft(initialDraft(null, next));
    setValidation(null);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const missing = specs.find((field) => field.required && !draft[field.key]?.trim());
    if (missing) { setValidation(`请填写${missing.label}`); return; }
    const value = Object.fromEntries(specs.flatMap((field) => {
      const raw = draft[field.key]?.trim() ?? "";
      if (!raw) return [];
      return [[field.key, field.list ? raw.split("\n").map((item) => item.trim()).filter(Boolean) : raw]];
    }));
    setValidation(null);
    await onSave({
      category,
      value,
      expectedVersion: card?.version ?? 0,
      relations: card ? [
        ...card.linkedTo.map((item) => ({ relationType: "belongs_to" as const, targetClaimId: item.claimId })),
        ...card.usedIn.map((item) => ({ relationType: "used_in" as const, targetClaimId: item.claimId })),
      ] : [],
    });
  }

  return <div className="profile-editor-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <section className="profile-card-editor" data-category={category} role="dialog" aria-modal="true" aria-labelledby="profile-card-editor-title">
      <header>
        <div><span>{card ? "编辑资料" : "补充资料"}</span><h2 id="profile-card-editor-title">{card ? `编辑${categoryLabels[category]}` : "添加到个人画像"}</h2></div>
        <button type="button" aria-label="关闭编辑" onClick={onCancel}><X size={20} /></button>
      </header>
      <form onSubmit={(event) => void submit(event)}>
        <div className="profile-card-editor__body">
          {!card ? <label className="profile-card-editor__category">添加什么
            <select value={category} onChange={(event) => changeCategory(event.target.value as ProfileCardCategory)}>
              {(["project", "experience", "skill", "education", "certification", "achievement", "direction", "highlight", "summary", "link"] as ProfileCardCategory[]).map((item) => <option key={item} value={item}>{categoryLabels[item]}</option>)}
            </select>
          </label> : null}
          <div className="profile-card-editor__fields">{specs.map((field) => <label key={field.key} data-field={field.key} data-multiline={field.multiline || undefined}>
            <span>{field.label}{field.required ? <em>必填</em> : null}</span>
            {field.multiline ? <textarea rows={field.list ? 4 : 3} value={draft[field.key] ?? ""} placeholder={field.placeholder} onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))} />
              : <input type={field.type ?? "text"} value={draft[field.key] ?? ""} placeholder={field.placeholder} onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))} />}
          </label>)}</div>
          {validation || error ? <div className="profile-card-editor__error" role="alert"><AlertCircle size={16} />{validation ?? error}</div> : null}
        </div>
        <footer>
          {card && onDelete ? <Button type="button" variant="ghost" className="profile-card-editor__delete" disabled={busy} onClick={() => void onDelete()}><Trash2 size={16} />删除这条资料</Button> : null}
          <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>取消</Button>
          <Button type="submit" loading={busy}>保存</Button>
        </footer>
      </form>
    </section>
  </div>;
}
