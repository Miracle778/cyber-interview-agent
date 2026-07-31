from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
    JudgeViewPolicy,
)


QUESTION_CURATION_PACK = EvalPack(
    id="question-curation.v1",
    version=1,
    agent_family="question-curation",
    title="题目整理质量",
    dimensions=(
        EvalDimension("source_fidelity", "来源忠实度", "题目与答案能被来源证据支持。", 3),
        EvalDimension("coverage", "内容完整度", "题目覆盖材料中的可面试知识点。", 2),
        EvalDimension("deduplication", "去重质量", "没有无意义重复或近重复题。"),
        EvalDimension("zero_item_compatibility", "零题兼容", "无有效题目时能够安全结束。"),
        EvalDimension("partial_success", "部分成功保留", "局部失败不会丢失已完成成果。", 2),
    ),
    required_evidence_event_types=frozenset(
        {"execution.started", "model.request", "model.response"}
    ),
    rules=(
        DeterministicRule(
            "trace_complete",
            "Trace 完整",
            "关键请求与响应事件必须可验证。",
            frozenset({"model.request", "model.response"}),
            True,
        ),
        DeterministicRule(
            "terminal_outcome",
            "终态明确",
            "运行必须具备可解释的终态事件。",
            frozenset({"execution.completed", "execution.failed"}),
        ),
    ),
    judge=JudgeContract(
        "question-curation-judge.v1",
        "依据冻结证据逐维评分，引用事件或 Artifact 哈希；说明不确定项，不推测未保存内容。",
    ),
)


QUESTION_CURATION_V2_PACK = EvalPack(
    id="question-curation.v2",
    version=2,
    agent_family="question-curation",
    title="题目整理业务结果质量",
    evaluation_contract_version=2,
    task_type="question_curation",
    dimensions=(
        EvalDimension(
            "material_processing_completeness",
            "材料处理完整性",
            "所有处理单元都有完成、跳过、失败或待处理归属。",
        ),
        EvalDimension(
            "explicit_question_recognition",
            "明确题目识别",
            "仅在存在可靠分母时判断原文明示题目是否被识别。",
        ),
        EvalDimension(
            "candidate_completeness",
            "候选完整性",
            "候选具备进入确认流程所需的题干、答案语义、来源和状态。",
        ),
        EvalDimension(
            "question_source_consistency",
            "题目来源一致性",
            "题干忠实表达材料主题且不虚构个人事实。",
        ),
        EvalDimension(
            "source_answer_fidelity",
            "原文答案忠实度",
            "只评价明确标记为来自材料的答案内容。",
        ),
        EvalDimension(
            "model_completion_quality",
            "模型补全质量",
            "模型补充正确、有用且不过度确定。",
        ),
        EvalDimension(
            "completion_transparency",
            "补全透明度",
            "原文答案与模型补充在持久化和展示中边界清楚。",
        ),
        EvalDimension(
            "duplicate_handling",
            "重复项处理",
            "疑似重复召回、关系判断和用户决定彼此分离。",
        ),
        EvalDimension(
            "zero_result_reasoning",
            "零结果合理性",
            "无题、待人工复核和处理失败被正确区分。",
        ),
    ),
    required_evidence_event_types=frozenset(),
    rules=(),
    judge=JudgeContract(
        "question-curation-judge.v2",
        "只根据最小业务结果视图评价适用维度；服从代码给出的适用性，"
        "不把明确标记的模型补充误判为来源不忠实，不推测缺失材料。",
        response_contract="JudgeResultV2",
    ),
    judge_view=JudgeViewPolicy(
        data_categories=(
            "taskIdentity",
            "curationCounters",
            "candidateContent",
            "fieldProvenance",
            "userDecision",
            "evidenceGaps",
        ),
        content_fields=(
            "question_text",
            "reference_answer",
            "source_answer",
            "supplemental_answer",
            "topics",
            "difficulty",
            "key_points",
            "follow_ups",
            "answer_basis",
            "material_support",
            "needs_review",
            "normalization_issues",
            "source_refs",
        ),
    ),
)
