from __future__ import annotations

from types import SimpleNamespace

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.application import InterviewRetrospectiveApplication
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.job_targets.repository import JobTargetRepository


def candidate_fixture(tmp_path, *, review=None, profile=None, drafts=None):
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    targets = JobTargetRepository(connection)
    repository = InterviewRetrospectiveRepository(connection)
    service = InterviewRetrospectiveService(
        workspace_id="w1", repository=repository, job_targets=targets
    )
    target = targets.create_target(
        workspace_id="w1",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
    )
    analysis_session = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.analysis",
        title="复盘分析",
        visibility="system",
    )
    chat_session = products.create_session(
        workspace_id="w1", kind="interview.retrospective.chat", title="复盘讨论"
    )
    retrospective = service.create(
        job_target_id=target.id,
        title="示例公司一面",
        round_label="一面",
        interview_date="2026-08-01",
        outcome="unrecorded",
        note="只允许进入结构化草稿的备注",
        analysis_session_id=analysis_session.id,
        chat_session_id=chat_session.id,
        idempotency_key="candidate-fixture",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="绝不能进入发布稿的原始转写 SECRET_RAW_TRANSCRIPT",
        file_name=None,
        idempotency_key="candidate-source",
    )
    cleanup = service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="a" * 64,
        idempotency_key="candidate-cleanup",
    )
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "面试官",
                "display_name": "面试官",
                "body": "如何治理缓存一致性？",
                "source_start": 0,
                "source_end": 11,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "候选人",
                "display_name": "我",
                "body": "通过消息表和补偿任务处理。",
                "source_start": 12,
                "source_end": 27,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="candidate-confirm-cleanup",
    )
    run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="b" * 64,
        context_snapshot={"targetId": target.id, "prompt": "SECRET_PROMPT"},
        idempotency_key="candidate-analysis",
    )
    segments = repository.list_segments(cleanup.id)
    questions = repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "technical_knowledge",
                "origin": "original",
                "question_text": "如何治理缓存一致性？",
                "question_segment_ids": (segments[0].id,),
                "answer_segment_ids": (segments[1].id,),
                "inference_basis": "",
                "confidence": 1.0,
            },
            {
                "ordinal": 2,
                "question_kind": "technical_knowledge",
                "origin": "inferred",
                "question_text": "缓存穿透如何治理？",
                "question_segment_ids": (),
                "answer_segment_ids": (segments[1].id,),
                "inference_basis": "根据回答推断",
                "confidence": 0.7,
            },
        ),
    )
    for question in questions:
        repository.save_question_analysis(
            run.id,
            question.id,
            output={
                "verdict": "improvable",
                "strengths": [{"summary": "识别了补偿机制"}],
                "improvements": [{"summary": "补充失败恢复边界"}],
                "omissions": [],
                "evidenceLevel": "internal_evidence",
                "confidence": 0.8,
                "improvementOutline": ["先说明一致性目标", "再说明补偿路径"],
                "suggestedAnswer": "先定义一致性目标，再采用消息表与幂等补偿。",
                "gaps": [
                    {
                        "kind": "knowledge",
                        "summary": "缺少缓存异常场景分类",
                        "evidenceSegmentIds": list(question.answer_segment_ids),
                    }
                ],
            },
            source_excerpt="SECRET_PROVIDER_RESPONSE",
            result_status=(
                "draft"
                if question.origin == "inferred"
                and question.decision_status == "pending"
                else "formal"
            ),
        )
    application = InterviewRetrospectiveApplication(
        workspace_id="w1",
        service=service,
        repository=repository,
        sessions=SimpleNamespace(),
        executions=SimpleNamespace(),
        products=products,
        agents=None,
        profile=profile,
        review=review,
        drafts=drafts,
    )
    return connection, application, retrospective, run, questions
