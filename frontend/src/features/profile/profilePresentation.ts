export function plainResumeExcerpt(value: string) {
  return value
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function isUsefulResumeExcerpt(value: string) {
  const excerpt = value.trim();
  return Boolean(
    excerpt
    && !excerpt.startsWith("---")
    && !/\bdocument_type\s*:/i.test(excerpt)
    && !/^#{1,3}\s+\S+\s*$/.test(excerpt)
    && !/\[(?:phone|email)\s+redacted\]/i.test(excerpt),
  );
}

export function profileClaimTypeLabel(value: string) {
  const labels: Record<string, string> = {
    skill: "技能",
    project: "项目经历",
    experience: "工作经历",
    education: "教育经历",
    link: "个人链接",
    achievement: "成果",
  };
  return labels[value] ?? value;
}

export function userFacingClaimReason(value: string) {
  return value
    .replace(/\bEvidence\b/gi, "简历原文")
    .replace(/\bClaim\b/gi, "简历要点");
}

const profileStructuredRequestPattern =
  /评估|诊断|优势|短板|差距|风险|分析(?:一下)?(?:我的)?画像|新增|添加|修改|更新|删除|去掉|拒绝|改成|改为|设为|调整/;

export function shouldStreamProfileAnswer(message: string) {
  return !profileStructuredRequestPattern.test(" ".concat(message.split(/\s+/).join(" ")).trim());
}

export function userFacingPlanSummary(value: string) {
  return userFacingClaimReason(value)
    .replace(/(?:依据)?已有证据\s+[0-9a-f-]{32,36}[，。]?/gi, "依据现有简历原文。")
    .replace(/\b[0-9a-f]{32}\b/gi, "一处简历原文")
    .replace(/\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi, "一处简历原文")
    .replace(/\s+([，。])/g, "$1");
}

export function userFacingProfileAnswer(value: string) {
  return userFacingClaimReason(value)
    .replace(/`?end_date`?\s*:\s*`?null`?/gi, "结束时间未填写")
    .replace(/\bend_date\b/gi, "结束时间")
    .replace(/`?null`?/gi, "未填写")
    .replace(/`([^`]+)`/g, "$1");
}
