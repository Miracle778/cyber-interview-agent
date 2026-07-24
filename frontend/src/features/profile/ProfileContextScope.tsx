import { ChevronDown, ShieldCheck } from "lucide-react";
import type { ProfileCardCategory, UnifiedProfile } from "./profileTypes";

const availableCategories: { id: ProfileCardCategory; label: string; key: keyof UnifiedProfile }[] = [
  { id: "summary", label: "个人简介", key: "summary" },
  { id: "direction", label: "求职方向", key: "directions" },
  { id: "experience", label: "工作经历", key: "experiences" },
  { id: "project", label: "项目经历", key: "projects" },
  { id: "skill", label: "技能", key: "skills" },
  { id: "education", label: "教育经历", key: "education" },
  { id: "certification", label: "证书", key: "certifications" },
  { id: "achievement", label: "成果", key: "achievements" },
];

function itemCount(profile: UnifiedProfile | null, key: keyof UnifiedProfile) {
  if (!profile) return 0;
  const value = profile[key];
  if (Array.isArray(value)) return value.length;
  return value ? 1 : 0;
}

export function ProfileContextScope({ profile, selected, onChange }: { profile: UnifiedProfile | null; selected: ProfileCardCategory[]; onChange: (categories: ProfileCardCategory[]) => void }) {
  const selectedLabels = availableCategories.filter((item) => selected.includes(item.id)).map((item) => item.label);
  return <details className="profile-context-scope">
    <summary>
      <span><ShieldCheck size={16} />正在使用：{selectedLabels.length ? selectedLabels.join("、") : "未选择资料"}</span>
      <small>只读取已确认内容</small>
      <ChevronDown size={16} />
    </summary>
    <div>
      <p>选择本次对话可参考的资料范围。待确认内容和敏感信息不会自动加入。</p>
      <fieldset>
        <legend className="sr-only">画像助手参考范围</legend>
        {availableCategories.map((item) => {
          const count = itemCount(profile, item.key);
          return <label key={item.id}>
            <input
              type="checkbox"
              checked={selected.includes(item.id)}
              onChange={(event) => onChange(event.target.checked ? [...selected, item.id] : selected.filter((value) => value !== item.id))}
            />
            <span>{item.label}<small>{count} 条</small></span>
          </label>;
        })}
      </fieldset>
    </div>
  </details>;
}
