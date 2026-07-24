import type { ProfileClaimProposal, ProfileClaimVersion } from "./profileTypes";

const fieldLabels: Record<string, string> = {
  category: "分类",
  name: "名称",
  title: "名称",
  role: "职责",
  company: "公司",
  organization: "组织",
  school: "学校",
  institution: "学校",
  degree: "学历",
  major: "专业",
  field: "专业",
  description: "具体内容",
  tech_stack: "使用技术",
  skills: "相关技能",
  sub_skills: "具体技能",
  proficiency: "熟练程度",
  confidence: "参考可信度",
  url: "链接",
  period: "时间",
  start_date: "开始时间",
  end_date: "结束时间",
};

function formatValue(key: string, item: unknown) {
  if (key === "confidence" && typeof item === "number") {
    if (item >= 0.85) return "高";
    if (item >= 0.65) return "中";
    return "较低";
  }
  if (Array.isArray(item)) return item.join("、");
  if (item && typeof item === "object") return Object.values(item).map(String).join("、");
  return String(item ?? "—");
}

function rows(value: Record<string, unknown> | null) {
  if (!value) return [];
  return Object.entries(value).filter(([key]) => key !== "category").map(([key, item]) => ({
    key,
    label: fieldLabels[key] ?? key.replaceAll("_", " "),
    value: formatValue(key, item),
  }));
}

export function ClaimDiff({ current, proposal }: { current: ProfileClaimVersion | null; proposal: ProfileClaimProposal }) {
  const currentData = rows(current?.value ?? null);
  const proposedData = rows(proposal.proposedValue);
  const currentRows = new Map(currentData.map((item) => [item.key, item.value]));
  const proposedRows = new Map(proposedData.map((item) => [item.key, item.value]));
  const labels = new Map([...currentData, ...proposedData].map((item) => [item.key, item.label]));
  const keys = [...new Set([...currentRows.keys(), ...proposedRows.keys()])];

  if (!current) {
    return <section className="claim-summary" aria-label="系统整理出的简历要点">
      <header><strong>系统整理出的内容</strong><span>确认后才会用于简历助手</span></header>
      <dl>{keys.map((key) => <div key={key}><dt>{labels.get(key)}</dt><dd>{proposedRows.get(key) ?? "—"}</dd></div>)}</dl>
    </section>;
  }

  return <section className="claim-diff" aria-label="当前内容与建议内容对比">
    <header><span>内容</span><strong>原来记录</strong><strong>本次建议</strong></header>
    {keys.map((key) => {
      const before = currentRows.get(key) ?? "—";
      const after = proposedRows.get(key) ?? "—";
      const changed = before !== after;
      return <div key={key} data-changed={changed || undefined}><span>{labels.get(key)}</span><p>{before}</p><p>{after}</p></div>;
    })}
  </section>;
}
