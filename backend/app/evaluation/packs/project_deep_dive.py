from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
)


PROJECT_DEEP_DIVE_PACK = EvalPack(
    id="project-deep-dive.v1",
    version=1,
    agent_family="project-deep-dive",
    title="项目深挖质量",
    dimensions=(
        EvalDimension("question_depth", "问题深度", "问题能够逐层追到职责、取舍和结果。", 2),
        EvalDimension("fact_consistency", "项目事实一致性", "叙事不超出已确认项目事实。", 3),
        EvalDimension("actionability", "建议可执行性", "改进建议可直接用于面试准备。", 2),
        EvalDimension("gap_visibility", "缺口可见性", "证据缺口被保留并要求用户确认。", 3),
    ),
    required_evidence_event_types=frozenset(
        {"execution.started", "model.request", "model.response"}
    ),
    rules=(
        DeterministicRule(
            "confirmed_facts_only",
            "事实边界",
            "评估输入必须引用冻结、已确认的项目事实。",
            frozenset({"execution.started", "model.response"}),
            True,
        ),
    ),
    judge=JudgeContract(
        "project-deep-dive-judge.v1",
        "根据冻结事实、问题与建议评分，引用哈希；证据不足时明确要求人工复核。",
    ),
)
