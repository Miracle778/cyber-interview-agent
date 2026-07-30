import type {
  EvaluationDimension,
  EvaluationFeedback,
  EvaluationRun,
} from "./evaluationTypes";


export type EvaluationTone = "success" | "neutral" | "warning" | "danger";

export interface EvaluationStatusMeta {
  label: string;
  tone: EvaluationTone;
}

export interface DimensionOutcome {
  label: string;
  tone: EvaluationTone;
}

export interface EvaluationSummary {
  passed: number;
  attention: number;
  failed: number;
  averageScore: number | null;
  humanVerdict: "accurate" | "incorrect" | "uncertain" | null;
}

const PACK_LABELS: Record<string, string> = {
  "job-analysis.v1": "岗位分析质量",
  "profile.v1": "画像助手质量",
  "project-deep-dive.v1": "项目深挖质量",
  "question-curation.v1": "题目整理质量",
  "review.v1": "复习评价质量",
};

const DIMENSION_LABELS: Record<string, string> = {
  actionability: "建议可执行性",
  background_exclusion: "背景排除",
  confirmed_facts_only: "事实边界",
  conflict_detection: "冲突识别",
  coverage: "内容完整度",
  correctness: "结论准确性",
  deduplication: "去重质量",
  evidence_alignment: "证据对齐",
  evidence_traceability: "证据可追溯",
  fact_consistency: "项目事实一致性",
  feedback_actionability: "反馈可执行性",
  follow_up_necessity: "追问必要性",
  gap_visibility: "缺口可见性",
  jd_region_detection: "JD 区域识别",
  key_point_coverage: "关键点覆盖",
  no_direct_profile_write: "无直接写入",
  partial_success: "部分成功保留",
  privacy_boundary: "隐私边界",
  progression_guard: "推进守卫",
  question_depth: "问题深度",
  requirement_atomicity: "要求原子性",
  source_fidelity: "来源忠实度",
  terminal_or_waiting: "状态可恢复",
  terminal_outcome: "终态明确",
  trace_complete: "Trace 完整",
  version_frozen: "JD 版本冻结",
  write_boundary: "写入边界",
  zero_item_compatibility: "零题兼容",
};

const STATUS_META: Record<string, EvaluationStatusMeta> = {
  completed: { label: "评估完成", tone: "success" },
  failed: { label: "评估失败", tone: "danger" },
  pending: { label: "等待评估", tone: "neutral" },
  queued: { label: "等待评估", tone: "neutral" },
  running: { label: "评估中", tone: "neutral" },
};

const SUCCESS_STATUSES = new Set(["passed", "pass", "ok", "valid"]);
const FAILURE_STATUSES = new Set(["failed", "fail", "error", "invalid", "missing"]);

function readableIdentifier(value: string): string {
  const normalized = value
    .replace(/\.v\d+$/i, "")
    .replace(/[-_.]+/g, " ")
    .trim();
  if (!normalized) return "未命名";
  return normalized
    .split(/\s+/)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function evaluationPackLabel(id: string): string {
  return PACK_LABELS[id] ?? readableIdentifier(id);
}

export function dimensionLabel(id: string): string {
  return DIMENSION_LABELS[id] ?? readableIdentifier(id);
}

export function evaluationStatusMeta(status: string): EvaluationStatusMeta {
  return STATUS_META[status] ?? {
    label: readableIdentifier(status),
    tone: "neutral",
  };
}

export function dimensionOutcome(dimension: EvaluationDimension): DimensionOutcome {
  const normalizedStatus = dimension.status.toLowerCase();
  if (FAILURE_STATUSES.has(normalizedStatus)) {
    return { label: "未通过", tone: "danger" };
  }
  if (dimension.score !== null) {
    if (dimension.score >= 85) return { label: "表现良好", tone: "success" };
    if (dimension.score >= 70) return { label: "基本稳定", tone: "neutral" };
    if (dimension.score >= 50) return { label: "需要关注", tone: "warning" };
    return { label: "风险较高", tone: "danger" };
  }
  if (SUCCESS_STATUSES.has(normalizedStatus)) {
    return { label: "已通过", tone: "success" };
  }
  return { label: readableIdentifier(dimension.status), tone: "neutral" };
}

export function summarizeEvaluation(
  run: EvaluationRun,
  feedback: EvaluationFeedback[] = [],
): EvaluationSummary {
  const result = run.dimensions.reduce(
    (summary, item) => {
      const outcome = dimensionOutcome(item);
      if (outcome.tone === "danger") summary.failed += 1;
      else if (outcome.tone === "warning") summary.attention += 1;
      else summary.passed += 1;
      if (item.score !== null) summary.scores.push(item.score);
      return summary;
    },
    { passed: 0, attention: 0, failed: 0, scores: [] as number[] },
  );
  const latestFeedback = [...feedback].sort((left, right) => right.version - left.version)[0];
  const verdict = latestFeedback?.verdict;

  return {
    passed: result.passed,
    attention: result.attention,
    failed: result.failed,
    averageScore: result.scores.length
      ? Math.round(result.scores.reduce((sum, score) => sum + score, 0) / result.scores.length)
      : null,
    humanVerdict: verdict === "accurate" || verdict === "incorrect" || verdict === "uncertain"
      ? verdict
      : null,
  };
}

export function formatEvaluationVersion(run: EvaluationRun): string {
  return `${evaluationPackLabel(run.evalPackId)} · v${run.evalPackVersion}`;
}
