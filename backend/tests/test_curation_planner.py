from collections import Counter

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.review.curation_planner import (
    CurationPlanningError,
    plan_curation_discovery,
)
from app.review.curation_sections import SourceSection, section_sources
from app.review.repository import ReviewRepository


def _assignment_counts(plan) -> Counter[str]:
    return Counter(
        ref
        for unit in (*plan.deterministic_units, *plan.model_units)
        for ref in (
            unit.source_refs
            if hasattr(unit, "source_refs")
            else tuple(section.ref for section in unit.sections)
        )
    )


def test_planner_extracts_question_ranges_without_promoting_answer_lists() -> None:
    source = (
        "s1:database.md\n"
        "这是一段需要模型识别的背景说明。\n\n"
        "# 什么是 MVCC？\nMVCC 是多版本并发控制。\n"
        "1. 一致性读\n"
        "2. 当前读\n\n"
        "**如何避免幻读？**\n需要结合隔离级别说明。\n"
        "3、索引只是答案列表项"
    )
    sections = section_sources((source,))

    plan = plan_curation_discovery(sections)

    assert [unit.seeds[0].question_text for unit in plan.deterministic_units] == [
        "什么是 MVCC？",
        "如何避免幻读？",
    ]
    assert [len(unit.source_refs) for unit in plan.deterministic_units] == [3, 2]
    assert len(plan.model_units) == 1
    assert tuple(section.ref for section in plan.model_units[0].sections) == (
        "s1#section-0001",
    )
    assert all(
        seed.source_ref == seed.source_refs[0]
        for unit in plan.deterministic_units
        for seed in unit.seeds
    )
    assert _assignment_counts(plan) == Counter({section.ref: 1 for section in sections})
    assert set(plan.covered_source_refs) == {section.ref for section in sections}


def test_planner_recognizes_explicit_and_numbered_question_lines() -> None:
    sections = section_sources((
        "s1:questions.md\n"
        "缓存会失效吗？\n答案。\n"
        "2) 为什么 B+ 树适合索引\n答案。\n"
        "3. 顺序扫描是上一题的答案项",
    ))

    plan = plan_curation_discovery(sections)

    assert [unit.seeds[0].question_text for unit in plan.deterministic_units] == [
        "缓存会失效吗？",
        "为什么 B+ 树适合索引",
    ]
    assert len(plan.deterministic_units) == 2
    assert plan.model_units == ()


def test_numbered_answer_prose_with_question_cues_stays_in_parent_range() -> None:
    sections = section_sources((
        "s1:answers.md\n"
        "# 为什么需要事务隔离？\n"
        "答案包括：\n"
        "1. 是否开启一致性视图取决于隔离级别\n"
        "2. 可见性机制通过版本链实现",
    ))

    plan = plan_curation_discovery(sections)

    assert [unit.seeds[0].question_text for unit in plan.deterministic_units] == [
        "为什么需要事务隔离？"
    ]
    assert plan.deterministic_units[0].source_refs == tuple(
        section.ref for section in sections
    )
    assert plan.model_units == ()


def test_plain_40k_source_uses_large_ordered_model_windows() -> None:
    sections = section_sources(("s1:plain.md\n" + "普通正文" * 10_000,))

    plan = plan_curation_discovery(sections)

    assert len(plan.model_units) in range(7, 11)
    assert plan.deterministic_units == ()
    assert all(
        sum(len(section.text) for section in unit.sections) <= 6_000
        for unit in plan.model_units
    )
    assert _assignment_counts(plan) == Counter({section.ref: 1 for section in sections})
    assert plan.covered_source_refs == tuple(section.ref for section in sections)
    assert [unit.input_digest for unit in plan.model_units] == [
        unit.input_digest for unit in plan_curation_discovery(sections).model_units
    ]


def test_planner_never_combines_different_sources_in_one_unit() -> None:
    sections = section_sources((
        "s1:first.md\n没有题目结构的第一份正文",
        "s2:second.md\n# 什么是 WAL？\nWrite-ahead logging。",
    ))

    plan = plan_curation_discovery(sections)

    for unit in plan.deterministic_units:
        assert len({ref.split("#", 1)[0] for ref in unit.source_refs}) == 1
    for unit in plan.model_units:
        assert len({section.source_id for section in unit.sections}) == 1


def test_mixed_plan_uses_one_repository_compatible_unit_index_namespace(
    tmp_path,
) -> None:
    sections = section_sources((
        "s1:mixed.md\n普通前言。\n\n# 什么是 WAL？\nWrite-ahead logging。",
        "s2:plain.md\n另一份没有题目结构的正文。",
    ))
    plan = plan_curation_discovery(sections)
    ordered_units = sorted(
        (*plan.deterministic_units, *plan.model_units),
        key=lambda unit: unit.unit_index,
    )

    assert [unit.unit_index for unit in ordered_units] == list(
        range(len(ordered_units))
    )
    assert [unit.unit_index for unit in plan.model_units] == [0, 2]
    assert [unit.unit_index for unit in plan.deterministic_units] == [1]

    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s1', 'w1', 'question.curate', 1, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r1', 's1', 'running')"
    )
    connection.commit()
    repository = ReviewRepository(connection)
    batch = repository.create_batch(
        workspace_id="w1", session_id="s1", run_id="r1", source_refs=("s1", "s2")
    )
    try:
        planned = [
            repository.plan_curation_work_item(
                batch_id=batch.id,
                stage="discovery",
                unit_index=unit.unit_index,
                input_digest=unit.input_digest,
                source_refs=(
                    unit.source_refs
                    if hasattr(unit, "source_refs")
                    else tuple(section.ref for section in unit.sections)
                ),
                processor_kind=(
                    "deterministic"
                    if hasattr(unit, "source_refs")
                    else "model"
                ),
            )
            for unit in ordered_units
        ]
    finally:
        connection.close()

    assert len({item.unit_index for item in planned}) == len(ordered_units)


def test_oversized_question_range_routes_overflow_to_model_coverage() -> None:
    sections = tuple(
        SourceSection(
            source_id="s1",
            ref=f"s1#section-{index:04d}",
            ordinal=index,
            text=("# 什么是事务隔离？" if index == 1 else f"答案项 {index}"),
            digest=f"{index:064x}",
        )
        for index in range(1, 36)
    )

    plan = plan_curation_discovery(sections)

    assert len(plan.deterministic_units) == 1
    assert len(plan.deterministic_units[0].source_refs) == 32
    assert plan.deterministic_units[0].seeds[0].source_refs == list(
        plan.deterministic_units[0].source_refs
    )
    assert [section.ref for unit in plan.model_units for section in unit.sections] == [
        "s1#section-0033",
        "s1#section-0034",
        "s1#section-0035",
    ]
    assert _assignment_counts(plan) == Counter({section.ref: 1 for section in sections})


def test_planner_rejects_duplicate_atomic_refs_with_stable_error() -> None:
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)

    with pytest.raises(CurationPlanningError, match="invalid source coverage") as error:
        plan_curation_discovery((section, section))

    assert error.value.code == "curation_discovery_plan_invalid"
