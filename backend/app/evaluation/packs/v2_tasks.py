from __future__ import annotations

from app.evaluation.contracts import (
    EvalDimension,
    EvalPack,
    JudgeContract,
    JudgeViewPolicy,
)


def _pack(
    *,
    pack_id: str,
    family: str,
    task_type: str,
    title: str,
    dimensions: tuple[tuple[str, str, str], ...],
    content_fields: tuple[str, ...],
    categories: tuple[str, ...],
) -> EvalPack:
    return EvalPack(
        id=pack_id,
        version=2,
        agent_family=family,
        title=title,
        dimensions=tuple(EvalDimension(*item) for item in dimensions),
        required_evidence_event_types=frozenset(),
        rules=(),
        judge=JudgeContract(
            prompt_id=f"{pack_id.removesuffix('.v2')}-judge.v2",
            instructions=(
                "只根据最小业务结果视图评价适用维度；服从代码给出的适用性，"
                "不推测缺失事实，不把未记录表述成用户没有，不执行任何业务写入。"
            ),
            response_contract="JudgeResultV2",
        ),
        evaluation_contract_version=2,
        task_type=task_type,
        judge_view=JudgeViewPolicy(
            data_categories=categories,
            content_fields=content_fields,
        ),
    )


QUESTION_REVISION_V2_PACK = _pack(
    pack_id="question-revision.v2",
    family="question-revision",
    task_type="question_revision",
    title="单题改写业务结果质量",
    dimensions=(
        ("revision_intent", "改写意图", "是否正确识别用户要修改的内容与范围。"),
        ("instruction_following", "指令遵循", "改写结果是否满足明确指令。"),
        ("edit_scope_control", "编辑范围控制", "未要求的字段和内容没有被静默改动。"),
        ("question_identity", "题目核心保持", "措辞编辑没有改变题目的核心考点。"),
        ("provenance_boundary", "来源边界保持", "原文内容和模型补充的边界未被破坏。"),
        ("new_error_risk", "新增错误风险", "改写没有引入新的事实或技术错误。"),
        ("version_safety", "版本与并发安全", "改写结果与目标版本、用户决定和 Receipt 一致。"),
    ),
    content_fields=(
        "question_text", "reference_answer", "source_answer", "supplemental_answer",
        "topics", "key_points",
        "answer_basis", "source_refs", "correction_note",
    ),
    categories=("revisionInput", "beforeAfter", "fieldProvenance", "userDecision"),
)


REVIEW_ROUND_V2_PACK = _pack(
    pack_id="review-round.v2",
    family="review-round",
    task_type="review_round",
    title="复习轮次业务结果质量",
    dimensions=(
        ("key_point_decision", "关键点评价", "每个关键点的覆盖判断有真实回答依据。"),
        ("coverage_evidence", "覆盖证据", "覆盖状态可以定位到用户回答。"),
        ("follow_up_decision", "追问决定", "只有真实缺口需要追问。"),
        ("follow_up_wording", "追问表达", "追问准确指向缺口且不重复。"),
        ("feedback_quality", "反馈质量", "先承认已覆盖内容，再说明缺口与下一步。"),
        ("assistance_boundary", "提示边界", "提示、解释和答案泄露程度符合用户意图。"),
    ),
    content_fields=(
        "question", "answer", "follow_up_answer", "evaluation", "coverage",
        "result_kind", "hint_level", "answer_revisions", "skipped",
    ),
    categories=("frozenQuestion", "userAnswers", "keyPointCoverage", "assistance", "evaluation"),
)


REVIEW_SINGLE_V2_PACK = _pack(
    pack_id="review-single.v2",
    family="review-single",
    task_type="review_single",
    title="单题评价业务结果质量",
    dimensions=REVIEW_ROUND_V2_PACK.dimensions and tuple(
        (item.id, item.title, item.description)
        for item in REVIEW_ROUND_V2_PACK.dimensions
    ),
    content_fields=REVIEW_ROUND_V2_PACK.judge_view.content_fields,
    categories=REVIEW_ROUND_V2_PACK.judge_view.data_categories,
)


REVIEW_DISCUSSION_V2_PACK = _pack(
    pack_id="review-discussion.v2",
    family="review-discussion",
    task_type="review_discussion",
    title="深入讨论业务结果质量",
    dimensions=(
        ("direct_answer", "直接回答", "回答直接回应用户当前问题。"),
        ("technical_accuracy", "技术准确性", "技术解释正确且不过度确定。"),
        ("context_continuity", "上下文连续性", "回答承接当前会话而不串题。"),
        ("depth_fit", "深度适配", "解释深度符合用户意图。"),
        ("uncertainty_boundary", "不确定性边界", "不确定信息和来源边界被诚实表达。"),
        ("progress_isolation", "进度隔离", "讨论消息没有改变正式复习进度。"),
    ),
    content_fields=("role", "message_kind", "content", "resolution_status"),
    categories=("conversationTurns", "questionContext", "progressSnapshot"),
)


PROFILE_INGEST_V2_PACK = _pack(
    pack_id="profile-ingest.v2",
    family="profile-ingest",
    task_type="profile_ingest",
    title="画像提取业务结果质量",
    dimensions=(
        ("field_evidence_alignment", "字段证据对齐", "每个建议字段能回到对应 Evidence。"),
        ("support_type_boundary", "来源类型边界", "直接来源、规范化、推断和本人补充分离。"),
        ("conflict_relation", "冲突关系", "矛盾、时间变化、互补、重复和模糊被正确分类。"),
        ("proposal_preservation", "建议保留", "新建议不静默覆盖旧值或丢失来源。"),
    ),
    content_fields=("proposal_type", "target_claim_id", "proposed_value", "reason", "status"),
    categories=("claimProposal", "evidenceRefs", "conflictRelations", "userDecision"),
)


PROFILE_ASSESSMENT_V2_PACK = _pack(
    pack_id="profile-assessment.v2",
    family="profile-assessment",
    task_type="profile_assessment",
    title="画像评估业务结果质量",
    dimensions=(
        ("assessment_scope", "评估范围", "全画像、分类、Claim 或材料范围明确。"),
        ("missing_semantics", "缺失语义", "字段缺失、资料未记录和本次未评估被区分。"),
        ("gap_grounding", "差距依据", "Gap、风险和建议关联字段或 Claim 及判断依据。"),
        ("non_existence_inference", "不存在推断", "资料没写不被推断为用户没有该经历。"),
    ),
    content_fields=("base_profile_version", "result", "scope", "gap", "risk", "recommendation"),
    categories=("assessmentScope", "confirmedProfileRefs", "gapsAndRecommendations"),
)


PROFILE_ASSISTANT_V2_PACK = _pack(
    pack_id="profile-assistant.v2",
    family="profile-assistant",
    task_type="profile_assistant",
    title="画像助手业务结果质量",
    dimensions=(
        ("direct_answer", "直接回答", "回答直接解决用户当前请求。"),
        ("fact_grounding", "事实依据", "个人事实由确认资料或明确本人陈述支持。"),
        ("context_continuity", "上下文连续性", "回答承接本会话上下文。"),
        ("tool_necessity", "工具必要性", "只有确需检索时才调用只读 Tool。"),
        ("tool_usefulness", "工具有效性", "Tool 结果被用于回答且避免重复调用。"),
        ("proposal_wording", "建议状态表达", "待确认 Proposal 不被表述成已正式保存。"),
        ("privacy_scope", "隐私与范围", "回答遵守 Workspace、角色与隐私范围。"),
    ),
    content_fields=("role", "message_kind", "content", "plan_status", "tool_name", "tool_status"),
    categories=("conversationTurns", "toolAuditSummary", "proposalAndPlanStatus"),
)


PROFILE_WRITE_BOUNDARY_V2_PACK = _pack(
    pack_id="profile-write-boundary.v2",
    family="profile-write-boundary",
    task_type="profile_write_boundary",
    title="画像写入边界质量",
    dimensions=(
        ("proposal_required", "建议先行", "正式变更先形成结构化 Proposal。"),
        ("user_confirmation", "用户确认", "写入前存在明确用户确认。"),
        ("version_guard", "版本守卫", "expected version 防止覆盖并发更新。"),
        ("receipt_integrity", "回执完整", "每项执行结果有稳定 Receipt。"),
        ("workspace_boundary", "工作区边界", "所有资源归属同一 Workspace。"),
        ("status_wording", "状态文案", "面向用户的状态没有把待确认为已完成。"),
    ),
    content_fields=("operation", "target", "expected_version", "status", "receipt_id", "error_code"),
    categories=("actionPlan", "planItems", "userConfirmation", "receipts"),
)


JOB_REQUIREMENT_ANALYSIS_V2_PACK = _pack(
    pack_id="job-requirement-analysis.v2",
    family="job-requirement-analysis",
    task_type="job_requirement_analysis",
    title="岗位要求分析业务结果质量",
    dimensions=(
        ("clause_classification", "段落分类", "公司、岗位、团队、职责、要求、福利和未知正确分开。"),
        ("requirement_exclusion", "非要求排除", "输出要求不混入团队背景和福利。"),
        ("requirement_atomicity", "要求原子性", "不过拆、欠拆并保留限定词与 AND/OR。"),
        ("inference_boundary", "推断边界", "显式要求与系统准备建议分开。"),
        ("source_offsets", "原文定位", "quote 与文档 offset、版本严格一致。"),
        ("version_traceability", "版本追溯", "旧版本要求仍定位到对应旧 JD。"),
    ),
    content_fields=(
        "requirement_type", "priority", "text", "source_quote", "source_start",
        "source_end", "inferred", "confirmation_status", "preparation_status",
    ),
    categories=("jobDocumentIdentity", "requirements", "sourceLocators", "userDecision"),
)


PROJECT_DEEP_DIVE_COACHING_V2_PACK = _pack(
    pack_id="project-deep-dive-coaching.v2",
    family="project-deep-dive-coaching",
    task_type="project_deep_dive_coaching",
    title="项目深挖辅导业务结果质量",
    dimensions=(
        ("information_gain", "信息增益", "下一问针对真实信息缺口。"),
        ("turn_continuity", "轮次承接", "承接上一轮回答且不重复。"),
        ("single_focus", "单一重点", "一次只解决一个主要问题。"),
        ("fact_boundary", "事实边界", "用户事实、当轮陈述、推断和通用建议分开。"),
        ("high_risk_grounding", "高风险事实依据", "角色、指标、因果和时间线有依据。"),
        ("gap_actionability", "差距可执行", "Gap 有原因、下一步、完成条件、证据和优先级。"),
        ("gap_lifecycle", "差距生命周期", "Gap 使用稳定 ID 并保留状态变化。"),
    ),
    content_fields=(
        "artifact_kind", "payload", "gap_kind", "summary", "status",
        "section_kind", "content", "current_stage", "waiting_for_input",
    ),
    categories=("deepDiveState", "turnArtifacts", "narrativeSections", "gapLifecycle"),
)


PROJECT_QUESTION_GENERATION_V2_PACK = _pack(
    pack_id="project-question-generation.v2",
    family="project-question-generation",
    task_type="project_question_generation",
    title="项目题生成业务结果质量",
    dimensions=(
        ("project_fact_grounding", "项目事实依据", "题目基于已确认项目事实或明确缺口。"),
        ("interview_value", "面试价值", "题目能检验候选人的真实项目能力。"),
        ("answer_non_disclosure", "答案不泄露", "题干不直接暴露参考答案。"),
        ("dimension_fit", "维度适配", "维度是描述而非强制固定配额。"),
        ("duplicate_relation", "重复关系", "重复、同核心、父子和相关题被区分。"),
        ("catalog_traceability", "题库追溯", "确认后的题保留项目、岗位和深挖来源。"),
    ),
    content_fields=("dimension", "question", "duplicate_of_question_id", "review_candidate_id", "status"),
    categories=("projectIdentity", "generatedQuestions", "duplicateRelations", "catalogLinks"),
)


INTERVIEW_RETROSPECTIVE_V2_PACK = _pack(
    pack_id="interview-retrospective.v2",
    family="interview-retrospective",
    task_type="interview_retrospective",
    title="面试复盘业务结果质量",
    dimensions=(
        (
            "transcript_fidelity",
            "转写忠实与修订边界",
            "纠错保持事实、数字、职责和术语边界，并能追溯原文。",
        ),
        (
            "uncertainty_confirmation",
            "不确定项与人工确认",
            "低置信度术语、说话人和推断问题进入确认流程。",
        ),
        (
            "speaker_question_recovery",
            "说话人与问题恢复",
            "说话人判断合理，补全问题保守且明确标记为推断。",
        ),
        (
            "question_extraction_completeness",
            "问题提取完整性",
            "已确认文本中的问题被提取并保留可定位证据。",
        ),
        (
            "analysis_grounding",
            "分析依据与忠实度",
            "逐题结论基于回答和证据，不虚构技术细节或抬高职责。",
        ),
        (
            "recommendation_actionability",
            "改进建议可行动性",
            "建议具体、与问题相关并能指导下一次回答。",
        ),
        (
            "discussion_context",
            "讨论直接性与上下文",
            "讨论直接回答追问并正确使用选中题目和工具结果。",
        ),
        (
            "history_source_coverage",
            "历史检索来源覆盖",
            "检索命中、总结和报告都保留完整来源引用。",
        ),
        (
            "lifecycle_idempotency",
            "生命周期与幂等",
            "停止、重试、恢复、任务结束后返回的旧结果和重复写入符合状态机。",
        ),
    ),
    content_fields=(
        "mode",
        "text",
        "speaker_role",
        "inferred",
        "confidence",
        "question_text",
        "question_kind",
        "evidence",
        "analysis",
        "recommendations",
        "message_kind",
        "query",
        "matches",
        "report",
        "status",
    ),
    categories=(
        "transcript",
        "questions",
        "analyses",
        "discussion",
        "historySearch",
        "userDecisions",
    ),
)


V2_TASK_PACKS = (
    QUESTION_REVISION_V2_PACK,
    REVIEW_ROUND_V2_PACK,
    REVIEW_SINGLE_V2_PACK,
    REVIEW_DISCUSSION_V2_PACK,
    PROFILE_INGEST_V2_PACK,
    PROFILE_ASSESSMENT_V2_PACK,
    PROFILE_ASSISTANT_V2_PACK,
    PROFILE_WRITE_BOUNDARY_V2_PACK,
    JOB_REQUIREMENT_ANALYSIS_V2_PACK,
    PROJECT_DEEP_DIVE_COACHING_V2_PACK,
    PROJECT_QUESTION_GENERATION_V2_PACK,
    INTERVIEW_RETROSPECTIVE_V2_PACK,
)
