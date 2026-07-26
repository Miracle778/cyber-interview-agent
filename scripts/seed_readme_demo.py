#!/usr/bin/env python3
"""Seed an isolated, fictional workspace used by README screenshots.

Run from the repository root:

    cd backend
    uv run python ../scripts/seed_readme_demo.py \
      --workspace-root /private/tmp/cyber-interview-agent-readme-demo \
      --app-data-dir /private/tmp/cyber-interview-agent-readme-app \
      --reset --register

The script only resets a directory that already contains its own marker file.
All names, companies, projects, metrics and job descriptions are fictional.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import shutil
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.application.workspace_runtime import AgentApplication
from app.db.app_database import connect_app_database
from app.knowledge.source_registry import KnowledgeSourceService
from app.review.curation_seed_reconciliation import reconcile_curation_seed_tasks
from app.review.models import CurationSummary, QuestionSnapshot
from app.services.workspace_service import WorkspaceService

DEMO_WORKSPACE_ID = "readme-demo"
DEMO_MARKER = ".readme-demo-workspace"
DEMO_FILES = REPOSITORY_ROOT / "examples" / "readme-demo"


def _graph_factory(_kind: str, **dependencies):
    graph = StateGraph(dict)
    graph.add_node("complete", lambda state: state)
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


def _prepare_workspace(root: Path, *, reset: bool) -> Path:
    resolved = root.expanduser().resolve()
    if resolved == Path("/") or len(resolved.parts) < 4:
        raise ValueError("workspace root is too broad")
    marker = resolved / DEMO_MARKER
    if resolved.exists() and any(resolved.iterdir()):
        if not reset:
            raise ValueError(
                f"{resolved} is not empty; pass --reset for an existing README Demo"
            )
        if not marker.is_file():
            raise ValueError(
                f"refusing to reset {resolved}: {DEMO_MARKER} is missing"
            )
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "Fictional README Demo workspace. Safe to recreate with the seed script.\n",
        encoding="utf-8",
    )
    return resolved


async def _add_sources(root: Path, workspace_id: str) -> dict[str, str]:
    service = KnowledgeSourceService(root, workspace_id=workspace_id)
    result: dict[str, str] = {}
    for filename in (
        "resume.md",
        "backend-platform-jd.md",
        "agent-application-jd.md",
        "messy-interview-notes.md",
    ):
        content = (DEMO_FILES / filename).read_bytes()
        source = await service.create(
            original_filename=filename,
            content_type="text/markdown",
            content=content,
        )
        result[filename] = source.id
    return result


def _add_profile(
    application: AgentApplication, workspace_id: str
) -> dict[str, str]:
    profile = application.profile(workspace_id)
    records: dict[str, str] = {}
    cards = (
        (
            "summary",
            {
                "text": "5 年后端与平台工程经验，擅长把复杂业务拆成可恢复、可观测的工程流程，正在向 AI Agent 应用工程拓展。"
            },
            "profile-summary",
        ),
        (
            "direction",
            {
                "name": "后端平台 / AI Agent 应用工程师",
                "description": "以平台工程能力为主线，补齐工具编排、评测和长期运行经验。",
            },
            "profile-direction",
        ),
        (
            "experience",
            {
                "organization": "云杉科技",
                "title": "后端平台工程师",
                "period": "2021.07—至今",
                "responsibilities": [
                    "负责仓储履约、设备数据和内部报表平台的核心服务设计",
                    "建设任务状态机、失败重试、幂等写入和链路追踪能力",
                ],
                "achievements": [
                    "推动接口契约、灰度发布和故障复盘规范落地",
                    "支撑多个业务团队稳定交付平台能力",
                ],
            },
            "profile-experience",
        ),
        (
            "project",
            {
                "name": "智能仓储履约平台",
                "period": "2022—2024",
                "background": "面向多仓、多货主的订单履约与库存协同平台。",
                "role": "核心后端工程师",
                "responsibilities": ["订单编排", "库存预占", "补偿任务", "异常恢复"],
                "key_actions": [
                    "将履约链路拆分为可重放状态机",
                    "通过幂等键和补偿任务处理跨服务失败",
                ],
                "tech_stack": ["Python", "FastAPI", "PostgreSQL", "Redis", "Kafka"],
                "results": ["高峰期失败订单人工处理比例从 7.8% 降至 1.6%"],
            },
            "project-warehouse",
        ),
        (
            "project",
            {
                "name": "IoT 设备数据平台",
                "period": "2021—2023",
                "background": "接入 12 万台设备的遥测与告警数据。",
                "role": "后端工程师",
                "responsibilities": ["数据接入", "时序聚合", "告警去重"],
                "key_actions": ["优化 Kafka 分区和批处理", "设计冷热数据分层"],
                "tech_stack": ["Java", "Kafka", "PostgreSQL", "ClickHouse"],
                "results": ["高峰写入延迟降低 43%"],
            },
            "project-iot",
        ),
        (
            "project",
            {
                "name": "多租户报表中心",
                "period": "2023—2025",
                "background": "为 20 余个业务团队提供统一指标与异步导出。",
                "role": "项目负责人",
                "responsibilities": ["查询编排", "权限隔离", "资源配额"],
                "key_actions": ["设计租户级限流", "统一指标口径和审计日志"],
                "tech_stack": ["Python", "Celery", "PostgreSQL", "Redis"],
                "results": ["报表重复开发需求减少约 55%"],
            },
            "project-reporting",
        ),
        (
            "project",
            {
                "name": "工单分类与知识检索助手",
                "period": "2025",
                "background": "使用向量检索和结构化提示词推荐工单分类与处理知识。",
                "role": "个人验证项目",
                "responsibilities": ["样本整理", "检索链路", "人工确认流程"],
                "key_actions": ["构建离线样本集", "记录检索命中与人工修正"],
                "tech_stack": ["Python", "FastAPI", "Vector Search", "LLM API"],
                "results": ["完成离线验证，但尚未形成长期运行的 Agent 工程经验"],
            },
            "project-agent-assistant",
        ),
        (
            "education",
            {
                "school": "华南理工大学",
                "degree": "本科",
                "major": "软件工程",
                "period": "2017.09—2021.06",
            },
            "profile-education",
        ),
    )
    for claim_type, value, command_id in cards:
        version = profile.create_profile_card(
            claim_type=claim_type,
            value=value,
            command_id=f"readme-demo:{command_id}",
        )
        records[command_id] = version.claim_id
    for skill in ("Python", "Java", "FastAPI", "PostgreSQL", "Redis", "Kafka"):
        version = profile.create_profile_card(
            claim_type="skill",
            value={
                "name": skill,
                "self_assessment": "能够结合真实项目说明设计取舍与故障处理。",
            },
            command_id=f"readme-demo:skill:{skill.lower()}",
        )
        records[f"skill-{skill.lower()}"] = version.claim_id
    return records


async def _add_curation(
    application: AgentApplication,
    workspace_id: str,
    source_ids: dict[str, str],
) -> str:
    review = application.review(workspace_id)
    session = await application.create_session(
        workspace_id=workspace_id,
        kind="question.curate",
        title="后端与 Agent 面试随手记",
    )
    selected_sources = (source_ids["messy-interview-notes.md"],)
    review.repository.create_curation_session(
        workspace_id=workspace_id,
        session_id=session.id,
        source_refs=selected_sources,
    )
    batch = review.repository.create_batch(
        workspace_id=workspace_id,
        session_id=session.id,
        run_id=None,
        source_refs=selected_sources,
        status="review_pending",
    )
    discovery_digest = hashlib.sha256(
        (DEMO_FILES / "messy-interview-notes.md").read_bytes()
    ).hexdigest()
    discovery_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest=discovery_digest,
        source_refs=selected_sources,
    )
    discovery_item = review.repository.start_curation_work_item(discovery_item.id)
    questions = (
        (
            "可恢复任务如何避免重复写入？",
            "如果一个长任务在进程中断后恢复，如何避免已经完成的步骤再次产生副作用？",
            ("状态机", "幂等", "任务恢复"),
            "medium",
            (
                "持久化步骤状态和输入摘要",
                "为外部写入设计幂等键或执行回执",
                "恢复时跳过已完成且结果可验证的步骤",
            ),
            "source",
            "sufficient",
            False,
        ),
        (
            "Kafka 消费积压应该怎样排查？",
            "线上出现 Kafka 消费积压时，你会按什么顺序定位问题？",
            ("Kafka", "故障定位", "可观测性"),
            "medium",
            (
                "确认 lag、吞吐和消费耗时变化",
                "检查分区分配、消费者健康和下游依赖",
                "区分临时扩容与根因修复",
            ),
            "source",
            "sufficient",
            False,
        ),
        (
            "Agent 工作流中代码与模型如何分工？",
            "哪些步骤应该由确定性代码编排，哪些步骤适合交给模型判断？请给出需要人工确认的例子。",
            ("Agent", "HITL", "工作流"),
            "hard",
            (
                "确定性写入和权限边界由代码控制",
                "语义理解、归纳和开放式评估由模型完成",
                "高影响资产变更进入人工确认",
            ),
            "source",
            "sufficient",
            False,
        ),
        (
            "Message 与 Execution 为什么要分开？",
            "模型失败或用户停止执行后，如何保证重试不会污染后续上下文？",
            ("Agent", "上下文", "失败恢复"),
            "hard",
            (
                "消息表达用户语义，执行表达一次运行尝试",
                "失败执行可重试但不重复创建用户消息",
                "未解决消息需要明确的 active、unresolved 或 abandoned 状态",
            ),
            "mixed",
            "partial",
            True,
        ),
    )
    review.repository.complete_curation_work_item(
        discovery_item.id,
        output={
            "seeds": [
                {
                    "question_text": question_text,
                    "source_ref": selected_sources[0],
                    "source_refs": list(selected_sources),
                }
                for _, question_text, *_ in questions
            ]
        },
    )
    reconcile_curation_seed_tasks(review.repository, batch.id)
    seed_tasks = review.repository.list_curation_seed_tasks(batch.id)
    if len(seed_tasks) != len(questions):
        raise RuntimeError("README demo seed task planning changed")
    summary_items: list[dict[str, object]] = []
    for index, (
        title,
        text,
        topics,
        difficulty,
        key_points,
        answer_basis,
        material_support,
        needs_review,
    ) in enumerate(questions, start=1):
        question_id = f"readme-demo-question-{index}"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed_task = seed_tasks[index - 1]
        claimed = review.repository.claim_curation_seed_tasks(
            batch.id,
            statuses=("pending",),
            limit=1,
        )
        if len(claimed) != 1 or claimed[0].id != seed_task.id:
            raise RuntimeError("README demo seed task claim order changed")
        seed_task = review.repository.complete_curation_seed_task(
            seed_task.id,
            expected_version=claimed[0].version,
            status="degraded" if needs_review else "completed",
            candidate={
                "title": title,
                "question_text": text,
                "reference_answer": "；".join(key_points) + "。",
                "topics": list(topics),
                "difficulty": difficulty,
                "key_points": list(key_points),
                "follow_ups": ["请结合你做过的项目说明一次真实取舍。"],
                "source_refs": list(selected_sources),
                "correction_note": (
                    "答案包含少量通用补充，发布前建议核对。"
                    if needs_review
                    else "题目与答案均可由原资料直接支撑。"
                ),
            },
            answer_basis=answer_basis,
            material_support=material_support,
            needs_review=needs_review,
            normalization_issues=(),
        )
        snapshot = QuestionSnapshot(
            question_id=question_id,
            document_id=f"readme-demo-document-{index}",
            content_hash=digest,
            title=title,
            question_text=text,
            reference_answer="；".join(key_points) + "。",
            topics=topics,
            difficulty=difficulty,
            key_points=key_points,
            follow_ups=("请结合你做过的项目说明一次真实取舍。",),
        )
        candidate = review.repository.save_candidate(
            batch_id=batch.id,
            question=snapshot,
            draft_id=None,
            source_refs=selected_sources,
            correction_note=(
                "答案包含少量通用补充，发布前建议核对。"
                if needs_review
                else "题目与答案均可由原资料直接支撑。"
            ),
            status="review_pending",
            candidate_id=f"readme-demo-candidate-{index}",
        )
        # `save_candidate` is also used by legacy imports and therefore keeps
        # conservative quality defaults. The README fixture has already
        # completed the real seed-quality lifecycle above, so mirror that
        # durable result onto the linked candidate row.
        review.repository._connection.execute(
            "UPDATE review_question_candidates SET seed_task_id = ?, "
            "answer_basis = ?, material_support = ?, needs_review = ?, "
            "normalization_issues_json = '[]' WHERE id = ?",
            (
                seed_task.id,
                answer_basis,
                material_support,
                int(needs_review),
                candidate.id,
            ),
        )
        review.repository._connection.commit()
        summary_items.append(
            {
                "ordinal": index,
                "candidateId": candidate.id,
                "title": title,
                "topics": topics,
                "difficulty": difficulty,
                "sourceCount": 1,
                "recommendation": "recommend_confirm",
            }
        )
    current = review.repository.get_curation_session(session.id)
    review.repository.replace_curation_summary(
        session.id,
        expected_version=current.summary_version,
        summary=CurationSummary(items=tuple(summary_items)),
    )
    review.repository.update_curation_progress(
        session.id,
        stage="waiting_for_command",
        completed_units=len(questions),
        total_units=len(questions),
        active_batch_id=batch.id,
    )
    return session.id


async def _add_job_targets(
    application: AgentApplication,
    workspace_id: str,
    profile_ids: dict[str, str],
) -> dict[str, str]:
    targets = application.job_targets(workspace_id)
    training = application.job_training(workspace_id)
    result: dict[str, str] = {}
    definitions = (
        (
            "backend",
            "高级后端平台工程师",
            "5 年以上",
            "星环零售",
            "backend-platform-jd.md",
            "project-warehouse",
        ),
        (
            "agent",
            "AI Agent 应用工程师",
            "3—6 年",
            "拾光智能",
            "agent-application-jd.md",
            "project-agent-assistant",
        ),
    )
    for key, role, seniority, company, filename, core_project_key in definitions:
        target = targets.create_target(
            role_name=role,
            seniority=seniority,
            company_name=company,
            source_url=None,
            idempotency_key=f"readme-demo:target:{key}",
        )
        document = targets.create_document_version(
            target.id,
            source_kind="jd_text",
            body=(DEMO_FILES / filename).read_text(encoding="utf-8"),
            idempotency_key=f"readme-demo:jd:{key}",
        )
        target = targets.confirm_document_version(
            target.id,
            document.id,
            expected_version=target.version,
            idempotency_key=f"readme-demo:jd-confirm:{key}",
        )
        analysis = await training.start_analysis(target.id)
        targets.confirm_safe_requirements(
            target.id,
            document_version_id=document.id,
            idempotency_key=f"readme-demo:requirements:{key}",
        )
        target = targets.get_target(target.id)
        supplementary = (
            (profile_ids["project-iot"],)
            if key == "backend"
            else (profile_ids["project-warehouse"],)
        )
        targets.set_project_priorities(
            target.id,
            core_project_id=profile_ids[core_project_key],
            supplementary_project_ids=supplementary,
            expected_version=target.version,
            idempotency_key=f"readme-demo:projects:{key}",
        )
        result[key] = target.id
        result[f"{key}-analysis"] = str(analysis["id"])

    dive = await training.create_deep_dive(
        result["agent"], profile_ids["project-agent-assistant"]
    )
    for answer in (
        "这个项目用于验证工单分类与知识检索。我负责样本整理、检索链路和人工确认流程，目标是先验证推荐是否可靠，而不是直接自动处理工单。",
        "我把检索结果、模型建议和人工选择分开记录。当前只有离线样本命中率与人工修正记录，缺少线上工具编排、系统化评测和长期运行数据。",
    ):
        dive = await training.answer_deep_dive(dive["id"], answer)
    result["deep-dive"] = dive["id"]
    result["deep-dive-session"] = dive["sessionId"]
    return result


async def seed(args: argparse.Namespace) -> None:
    root = _prepare_workspace(Path(args.workspace_root), reset=args.reset)
    registered_id = None
    if args.register:
        if not args.app_data_dir:
            raise ValueError("--register requires --app-data-dir")
        connection = connect_app_database(Path(args.app_data_dir))
        try:
            workspace = WorkspaceService(connection).register(
                str(root), display_name="README Demo"
            )
            registered_id = workspace.id
        finally:
            connection.close()
    workspace_id = registered_id or DEMO_WORKSPACE_ID
    source_ids = await _add_sources(root, workspace_id)
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: (workspace_id,),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    try:
        profile_ids = _add_profile(application, workspace_id)
        curation_session_id = await _add_curation(
            application, workspace_id, source_ids
        )
        target_ids = await _add_job_targets(
            application, workspace_id, profile_ids
        )
    finally:
        await application.close()

    print(f"workspace_root={root}")
    print(f"runtime_workspace_id={workspace_id}")
    print(f"registered_workspace_id={registered_id or 'not-registered'}")
    print(f"curation_session_id={curation_session_id}")
    print(f"agent_target_id={target_ids['agent']}")
    print(f"deep_dive_session_id={target_ids['deep-dive-session']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--app-data-dir")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(seed(parse_args()))
