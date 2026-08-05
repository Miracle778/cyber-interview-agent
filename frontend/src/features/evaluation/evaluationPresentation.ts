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
  "question-curation.v2": "题目整理业务结果质量",
  "question-revision.v2": "单题改写业务结果质量",
  "review-round.v2": "复习轮次业务结果质量",
  "review-single.v2": "单题评价业务结果质量",
  "review-discussion.v2": "深入讨论业务结果质量",
  "interview-retrospective.v2": "面试复盘业务结果质量",
  "profile-ingest.v2": "画像提取业务结果质量",
  "profile-assessment.v2": "画像评估业务结果质量",
  "profile-assistant.v2": "画像助手业务结果质量",
  "profile-write-boundary.v2": "画像写入边界检查",
  "job-requirement-analysis.v2": "岗位要求分析业务结果质量",
  "project-deep-dive-coaching.v2": "项目深挖辅导业务结果质量",
  "project-question-generation.v2": "项目题生成业务结果质量",
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
  material_processing_completeness: "材料处理完整性",
  explicit_question_recognition: "明确题目识别",
  candidate_completeness: "候选完整性",
  question_source_consistency: "题目来源一致性",
  source_answer_fidelity: "原文答案忠实度",
  model_completion_quality: "模型补全质量",
  completion_transparency: "补全透明度",
  duplicate_handling: "重复项处理",
  zero_result_reasoning: "零结果合理性",
  revision_intent: "改写意图",
  instruction_following: "指令遵循",
  edit_scope_control: "编辑范围控制",
  question_identity: "题目核心保持",
  provenance_boundary: "来源边界保持",
  new_error_risk: "新增错误风险",
  version_safety: "版本与并发安全",
  key_point_decision: "关键点评价",
  coverage_evidence: "覆盖证据",
  follow_up_decision: "追问决定",
  follow_up_wording: "追问表达",
  feedback_quality: "反馈质量",
  assistance_boundary: "提示边界",
  direct_answer: "直接回答",
  technical_accuracy: "技术准确性",
  context_continuity: "上下文连续性",
  depth_fit: "深度适配",
  uncertainty_boundary: "不确定性边界",
  progress_isolation: "进度隔离",
  field_evidence_alignment: "字段证据对齐",
  support_type_boundary: "来源类型边界",
  conflict_relation: "冲突关系",
  proposal_preservation: "建议保留",
  assessment_scope: "评估范围",
  missing_semantics: "缺失语义",
  gap_grounding: "差距依据",
  non_existence_inference: "不存在推断",
  fact_grounding: "事实依据",
  tool_necessity: "工具必要性",
  tool_usefulness: "工具有效性",
  proposal_wording: "建议状态表达",
  privacy_scope: "隐私与范围",
  proposal_required: "建议先行",
  user_confirmation: "用户确认",
  version_guard: "版本守卫",
  receipt_integrity: "回执完整",
  workspace_boundary: "工作区边界",
  status_wording: "状态文案",
  clause_classification: "段落分类",
  requirement_exclusion: "非要求排除",
  inference_boundary: "推断边界",
  source_offsets: "原文定位",
  version_traceability: "版本追溯",
  information_gain: "信息增益",
  turn_continuity: "轮次承接",
  single_focus: "单一重点",
  fact_boundary: "事实边界",
  high_risk_grounding: "高风险事实依据",
  gap_actionability: "差距可执行",
  gap_lifecycle: "差距生命周期",
  project_fact_grounding: "项目事实依据",
  transcript_fidelity: "转写忠实度",
  uncertainty_confirmation: "不确定项确认",
  speaker_question_recovery: "说话人与问题还原",
  question_extraction_completeness: "题目提取完整性",
  analysis_grounding: "分析证据支撑",
  recommendation_actionability: "改进建议可执行性",
  discussion_context: "复盘讨论上下文",
  history_source_coverage: "历史检索来源覆盖",
  lifecycle_idempotency: "运行生命周期一致性",
  interview_value: "面试价值",
  answer_non_disclosure: "答案不泄露",
  dimension_fit: "维度适配",
  duplicate_relation: "重复关系",
  catalog_traceability: "题库追溯",
  "question.answer_provenance_separation": "答案来源拆分",
  "question.zero_result_classification": "零结果分类",
  "review.progression_guard": "复习推进守卫",
  "review.discussion_progress_isolation": "讨论进度隔离",
  "profile.proposal_evidence": "画像建议依据",
  "profile.assessment_missing_semantics": "画像缺失语义",
  "profile.tool_budget": "画像工具预算",
  "profile.write_receipt_integrity": "画像写入回执",
  "profile.write_version_guard": "画像版本守卫",
  "job.source_locator_integrity": "JD 原文定位",
  "job.inference_boundary": "岗位推断边界",
  "project.gap_lifecycle": "项目差距生命周期",
  "project.question_catalog_link": "项目题入库关联",
  "retrospective.inferred_question_confirmation": "推断题人工确认",
  "retrospective.analysis_grounding": "复盘结论证据支撑",
  "retrospective.discussion_result_isolation": "讨论结果隔离",
  "retrospective.history_source_coverage": "历史检索来源覆盖",
  "runtime.workspace_ownership": "运行归属正确",
  "runtime.idempotent_terminal_writes": "结果不会重复写入",
  "runtime.count_conservation": "处理数量一致",
  "runtime.source_provenance": "结果来源可追溯",
  "runtime.source_version_integrity": "来源版本可核对",
  "runtime.late_result_protection": "任务结束后结果保护",
  "runtime.tool_write_boundary": "工具写入边界",
  "runtime.receipt_event_consistency": "业务结果与处理记录一致",
};

const RUNTIME_SUMMARIES: Record<string, {
  success: string;
  warning: string;
  danger: string;
}> = {
  "runtime.workspace_ownership": {
    success: "本次结果属于当前工作区和对应任务。",
    warning: "暂时无法完整确认本次结果与当前任务的归属关系。",
    danger: "本次结果与当前工作区或任务不一致。",
  },
  "runtime.idempotent_terminal_writes": {
    success: "本次没有发现重复保存的结果。",
    warning: "暂时无法确认重复执行是否会产生重复结果。",
    danger: "发现重复保存的结果，需要处理。",
  },
  "runtime.count_conservation": {
    success: "处理前后的数量一致，没有发现遗漏或重复。",
    warning: "暂时无法完整核对处理前后的数量。",
    danger: "处理前后的数量不一致，可能存在遗漏或重复。",
  },
  "runtime.source_provenance": {
    success: "结果保留了可追溯的来源。",
    warning: "部分结果暂时无法追溯到明确来源。",
    danger: "发现结果缺少必要的来源记录。",
  },
  "runtime.source_version_integrity": {
    success: "结果来源、版本和原文位置可以完整核对。",
    warning: "已有来源记录，但还不能完整确认对应版本和原文位置。",
    danger: "结果引用的来源或版本不一致。",
  },
  "runtime.late_result_protection": {
    success: "任务结束后返回的旧结果不会覆盖最终结果。",
    warning: "缺少任务状态记录，暂时无法核对结束后返回的旧结果是否已被拦住。",
    danger: "发现任务结束后返回的旧结果可能覆盖最终结果。",
  },
  "runtime.tool_write_boundary": {
    success: "工具调用与结果写入都在允许范围内。",
    warning: "暂时缺少完整记录，无法确认工具是否越界写入。",
    danger: "发现工具调用或结果写入超出允许范围。",
  },
  "runtime.receipt_event_consistency": {
    success: "业务结果与系统处理记录保持一致。",
    warning: "暂时缺少业务结果与系统处理记录的对应依据。",
    danger: "业务结果与系统处理记录不一致。",
  },
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
const ATTENTION_STATUSES = new Set(["inconclusive", "uncertain", "partial", "warning"]);

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
  return DIMENSION_LABELS[id] ?? "其他检查项";
}

export function isRuntimeDimension(id: string): boolean {
  return id.startsWith("runtime.");
}

export function dimensionUserSummary(dimension: EvaluationDimension): string {
  const runtime = RUNTIME_SUMMARIES[dimension.dimensionId];
  if (!runtime) {
    return dimension.summary || dimension.risks[0] || dimensionLabel(dimension.dimensionId);
  }
  const tone = dimensionOutcome(dimension).tone;
  return tone === "danger" ? runtime.danger : tone === "warning" ? runtime.warning : runtime.success;
}

export function evaluationStatusMeta(status: string): EvaluationStatusMeta {
  return STATUS_META[status] ?? {
    label: readableIdentifier(status),
    tone: "neutral",
  };
}

export function dimensionOutcome(dimension: EvaluationDimension): DimensionOutcome {
  if (dimension.applicability === "not_applicable") {
    return { label: "不适用", tone: "neutral" };
  }
  if (dimension.applicability === "insufficient_evidence") {
    return { label: "证据不足", tone: "warning" };
  }
  if (dimension.rating === "meets") {
    return { label: "符合要求", tone: "success" };
  }
  if (dimension.rating === "usable") {
    return { label: "基本可用", tone: "neutral" };
  }
  if (dimension.rating === "needs_review") {
    return { label: "建议复核", tone: "warning" };
  }
  if (dimension.rating === "severe") {
    return { label: "严重问题", tone: "danger" };
  }
  const normalizedStatus = dimension.status.toLowerCase();
  if (FAILURE_STATUSES.has(normalizedStatus)) {
    return { label: "未通过", tone: "danger" };
  }
  if (ATTENTION_STATUSES.has(normalizedStatus)) {
    return { label: "证据不足", tone: "warning" };
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

export function evaluationContractLabel(run: EvaluationRun): string {
  return run.evaluationContractVersion >= 2 ? "业务结果质检" : "初版质检";
}
