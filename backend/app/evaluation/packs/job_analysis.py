from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
)


JOB_ANALYSIS_PACK = EvalPack(
    id="job-analysis.v1",
    version=1,
    agent_family="job-analysis",
    title="岗位分析质量",
    dimensions=(
        EvalDimension("jd_region_detection", "JD 区域识别", "只把真实岗位要求区域纳入分析。", 2),
        EvalDimension("requirement_atomicity", "要求原子性", "复合要求被拆成可确认的独立项。", 3),
        EvalDimension("background_exclusion", "背景排除", "公司宣传与背景描述不会伪装成要求。", 2),
        EvalDimension("evidence_traceability", "证据可追溯", "要求能定位回 JD 版本与原文。", 3),
    ),
    required_evidence_event_types=frozenset(
        {"execution.started", "model.request", "model.response"}
    ),
    rules=(
        DeterministicRule(
            "version_frozen",
            "JD 版本冻结",
            "评估证据必须绑定不可变 JD 版本。",
            frozenset({"execution.started"}),
            True,
        ),
    ),
    judge=JudgeContract(
        "job-analysis-judge.v1",
        "依据冻结 JD 和结构化输出逐维评分，引用证据哈希并说明风险。",
    ),
)
