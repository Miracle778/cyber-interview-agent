import type {
  OperationSummary,
  TraceEventSummary,
} from "./observabilityTypes";

const OPERATION_NAMES: Record<string, string> = {
  execution_runtime: "运行任务",
  question_generation: "生成题目",
  question_discovery: "发现候选题",
  review_evaluation: "评估回答",
  report_generation: "生成报告",
  profile_generation: "整理个人画像",
  job_analysis: "分析岗位要求",
  project_deep_dive: "深入分析项目",
  review_round_evaluator: "回答评价",
  project_answer_evaluator: "项目回答评价",
};

const EVENT_NAMES: Record<string, string> = {
  "execution.started": "任务开始",
  "execution.completed": "任务完成",
  "execution.failed": "任务失败",
  "execution.cancelled": "任务已取消",
  "execution.interrupted": "任务已暂停",
  "model.request": "模型请求",
  "model.response": "模型响应",
  "model.error": "模型处理异常",
  "tool.started": "工具开始执行",
  "tool.completed": "工具执行完成",
  "tool.failed": "工具执行失败",
  "context.compacted": "上下文已压缩",
};

const KIND_NAMES: Record<OperationSummary["kind"], string> = {
  execution: "本次运行",
  agent: "Agent 处理",
  model: "模型调用",
  tool: "工具调用",
  graph: "处理步骤",
};

const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i;
const SCOPED_REVIEW_EVALUATOR = /^(review_round_evaluator|project_answer_evaluator):(\d+)$/;

export function operationKindLabel(kind: OperationSummary["kind"]) {
  return KIND_NAMES[kind];
}

export function friendlyOperationName(operation: OperationSummary) {
  const normalized = operation.name.trim().toLocaleLowerCase();
  const scopedEvaluation = normalized.match(SCOPED_REVIEW_EVALUATOR);
  if (scopedEvaluation) {
    if (operation.kind === "model") return "模型调用";
    return `第 ${Number(scopedEvaluation[2])} 题 · ${scopedEvaluation[1] === "project_answer_evaluator" ? "项目回答评价" : "回答评价"}`;
  }
  if (
    operation.kind === "model"
    && ["review_round_evaluator", "project_answer_evaluator"].includes(normalized)
  ) {
    return "模型调用";
  }
  if (OPERATION_NAMES[normalized]) return OPERATION_NAMES[normalized];
  if (UUID_LIKE.test(normalized)) return KIND_NAMES[operation.kind];
  return operation.name;
}

export function friendlyEventName(
  eventType: string,
  recovered = false,
  resumed = false,
) {
  if (eventType === "execution.started" && resumed) return "任务恢复";
  const name = EVENT_NAMES[eventType] ?? eventType;
  return recovered && isFailureEventType(eventType) ? `${name} · 已恢复` : name;
}

export function executionStartPresentation(
  event: TraceEventSummary,
  events: TraceEventSummary[],
): "start" | "recovery" | null {
  if (event.eventType !== "execution.started") return null;
  let sawStart = false;
  let failureSinceStart = false;
  for (const candidate of [...events].sort((left, right) => left.sequence - right.sequence)) {
    if (candidate.eventType === "execution.started") {
      const presentation = !sawStart
        ? failureSinceStart ? "recovery" : "start"
        : failureSinceStart
          ? "recovery"
          : null;
      if (candidate.eventId === event.eventId) return presentation;
      sawStart = true;
      failureSinceStart = false;
      continue;
    }
    if (isFailureEventType(candidate.eventType)) {
      failureSinceStart = true;
    }
  }
  return null;
}

export function isFailureEventType(eventType: string) {
  return /\.(?:failed|error)$/.test(eventType);
}

export function operationStatusLabel(
  operationStatus: string,
  executionStatus?: string,
  recovered = false,
) {
  if (operationStatus === "failed" && recovered) return "历史异常 · 已恢复";
  if (
    ["failed", "partial_success", "cancelled", "interrupted"].includes(
      executionStatus ?? "",
    )
    && ["queued", "running", "accepted"].includes(operationStatus)
  ) {
    return "未记录结束";
  }
  return null;
}

export function failureEventWasRecovered(
  event: TraceEventSummary,
  events: TraceEventSummary[],
) {
  return isFailureEventType(event.eventType)
    && events.some((candidate) =>
      candidate.eventType === "execution.started"
      && candidate.sequence > event.sequence,
    );
}

export function operationWasRecovered(
  operation: OperationSummary,
  events: TraceEventSummary[],
  operations: OperationSummary[] = [],
) {
  const operationIds = new Set([operation.id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const candidate of operations) {
      if (
        candidate.parentOperationId
        && operationIds.has(candidate.parentOperationId)
        && !operationIds.has(candidate.id)
      ) {
        operationIds.add(candidate.id);
        changed = true;
      }
    }
  }
  const latestFailureSequence = events.reduce(
    (latest, event) => operationIds.has(event.operationId)
      && isFailureEventType(event.eventType)
      ? Math.max(latest, event.sequence)
      : latest,
    -1,
  );
  return latestFailureSequence >= 0
    && events.some((event) =>
      event.eventType === "execution.started"
      && event.sequence > latestFailureSequence,
    );
}
