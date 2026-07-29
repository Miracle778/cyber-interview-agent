from app.evaluation.contracts import (
    DeterministicRule,
    EvalDimension,
    EvalPack,
    JudgeContract,
)


PROFILE_PACK = EvalPack(
    id="profile.v1",
    version=1,
    agent_family="profile",
    title="画像助手质量",
    dimensions=(
        EvalDimension("evidence_alignment", "Evidence 对齐", "画像结论能回到原始证据。", 3),
        EvalDimension("conflict_detection", "冲突识别", "矛盾信息被显式标记而非静默覆盖。", 2),
        EvalDimension("write_boundary", "写入边界", "未确认信息不会越权进入正式画像。", 3),
        EvalDimension("privacy_boundary", "隐私边界", "结果不会泄露密钥或无关私有内容。", 2),
    ),
    required_evidence_event_types=frozenset(
        {"execution.started", "model.request", "model.response"}
    ),
    rules=(
        DeterministicRule(
            "no_direct_profile_write",
            "无直接写入",
            "Judge 证据中不得出现评估侧领域写操作。",
            frozenset({"model.request", "model.response"}),
            True,
        ),
    ),
    judge=JudgeContract(
        "profile-judge.v1",
        "依据冻结材料证据与输出评分，逐项引用哈希；不补写画像，不推测缺失信息。",
    ),
)
