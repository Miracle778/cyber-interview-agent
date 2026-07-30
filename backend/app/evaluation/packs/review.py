from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
)


REVIEW_PACK = EvalPack(
    id="review.v1",
    version=1,
    agent_family="review",
    title="复习评价质量",
    dimensions=(
        EvalDimension("key_point_coverage", "关键点覆盖", "反馈能识别回答已覆盖与缺失的关键点。", 3),
        EvalDimension("follow_up_necessity", "追问必要性", "追问只用于补齐真实缺口。", 2),
        EvalDimension("progression_guard", "推进守卫", "未满足推进条件时不会提前进入下一题。", 3),
        EvalDimension("feedback_actionability", "反馈可执行性", "建议明确、具体且可继续练习。", 2),
    ),
    required_evidence_event_types=frozenset(
        {"execution.started", "model.request", "model.response"}
    ),
    rules=(
        DeterministicRule(
            "terminal_or_waiting",
            "状态可恢复",
            "运行必须产生可验证的评价响应或明确证据缺口。",
            frozenset({"model.response"}),
        ),
    ),
    judge=JudgeContract(
        "review-judge.v1",
        "只依据冻结回答、评价与 Trace 证据评分；引用哈希并说明不确定性，不生成隐藏推理。",
    ),
)
