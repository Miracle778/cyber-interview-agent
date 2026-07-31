import type { OperationSummary } from "./observabilityTypes";

const OPERATION_NAMES: Record<string, string> = {
  execution_runtime: "运行任务",
  question_generation: "生成题目",
  question_discovery: "发现候选题",
  review_evaluation: "评估回答",
  report_generation: "生成报告",
  profile_generation: "整理个人画像",
  job_analysis: "分析岗位要求",
  project_deep_dive: "深入分析项目",
};

const EVENT_NAMES: Record<string, string> = {
  "execution.started": "任务开始",
  "execution.completed": "任务完成",
  "execution.failed": "任务失败",
  "execution.cancelled": "任务已取消",
  "execution.interrupted": "任务已暂停",
  "model.request": "模型请求",
  "model.response": "模型响应",
  "model.error": "模型调用失败",
  "tool.started": "工具开始执行",
  "tool.completed": "工具执行完成",
  "tool.failed": "工具执行失败",
  "context.compacted": "上下文已压缩",
};

const KIND_NAMES: Record<OperationSummary["kind"], string> = {
  execution: "任务运行",
  agent: "Agent 处理",
  model: "模型调用",
  tool: "工具调用",
  graph: "处理步骤",
};

const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i;

export function operationKindLabel(kind: OperationSummary["kind"]) {
  return KIND_NAMES[kind];
}

export function friendlyOperationName(operation: OperationSummary) {
  const normalized = operation.name.trim().toLocaleLowerCase();
  if (OPERATION_NAMES[normalized]) return OPERATION_NAMES[normalized];
  if (UUID_LIKE.test(normalized)) return KIND_NAMES[operation.kind];
  return operation.name;
}

export function friendlyEventName(eventType: string) {
  return EVENT_NAMES[eventType] ?? eventType;
}

export function isFailureEventType(eventType: string) {
  return /\.(?:failed|error)$/.test(eventType);
}

export function operationStatusLabel(
  operationStatus: string,
  executionStatus?: string,
) {
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
