from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
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
