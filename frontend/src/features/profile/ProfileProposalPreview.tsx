import type { ProfileClaimProposal, ProfileClaimVersion } from "./profileTypes";

const labels: Record<string, string> = {
  name: "名称",
  title: "名称",
  role: "担任角色",
  company: "所在公司",
  organization: "所在组织",
  school: "学校",
  institution: "学校",
  degree: "学历",
  major: "专业",
  field: "专业",
  description: "主要内容",
  tech_stack: "使用技术",
  skills: "相关技能",
  sub_skills: "具体技能",
  proficiency: "熟练程度",
  url: "链接",
  period: "时间",
  start_date: "开始时间",
  end_date: "结束时间",
  result: "成果",
  results: "成果",
  highlights: "亮点",
};

const hiddenFields = new Set(["category", "confidence", "source", "source_kind", "evidence_ids"]);

function formatValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join("、");
  if (value && typeof value === "object") return Object.values(value).map(String).join("、");
  return String(value ?? "未填写");
}

function previewRows(value: Record<string, unknown>) {
  return Object.entries(value)
    .filter(([key, item]) => !hiddenFields.has(key) && item !== null && item !== "" && labels[key])
    .map(([key, item]) => ({ key, label: labels[key], value: formatValue(item) }));
}

export function ProfileProposalPreview({ current, proposal }: { current: ProfileClaimVersion | null; proposal: ProfileClaimProposal }) {
  const proposed = previewRows(proposal.proposedValue);
  const before = current ? new Map(previewRows(current.value).map((item) => [item.key, item.value])) : null;

  return <section className="profile-proposal-preview" aria-label="确认后个人画像会显示的内容">
    <header><strong>确认后会这样显示</strong><span>{current ? "高亮显示本次变化" : "你可以先核对内容和来源"}</span></header>
    <dl>{proposed.map((item) => {
      const changed = before ? before.get(item.key) !== item.value : false;
      return <div key={item.key} data-changed={changed || undefined}>
        <dt>{item.label}</dt>
        <dd>{item.value}</dd>
        {changed && before?.get(item.key) ? <small>原来：{before.get(item.key)}</small> : null}
      </div>;
    })}</dl>
  </section>;
}
