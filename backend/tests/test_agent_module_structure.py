from pathlib import Path

import pytest

from app.agents.agent_invocation import isolated_thread_config
from app.agents.context import AgentContext
from app.agents.prompts.prompt_spec import PromptSpec
from app.agents.prompts.question_curation_prompts import (
    QUESTION_CURATION_PROMPT,
    render_question_curation_input,
)
from app.agents.prompts.single_review_prompts import (
    SINGLE_REVIEW_EVALUATION_PROMPT,
    render_single_evaluation_input,
)


def test_agent_and_middleware_modules_have_explicit_names() -> None:
    backend = Path(__file__).parents[1]
    agents = backend / "app" / "agents"
    middleware = backend / "app" / "middleware"

    assert not (agents / "review.py").exists()
    assert not (agents / "question_curation.py").exists()
    assert (agents / "single_review_agents.py").is_file()
    assert (agents / "question_curation_agent.py").is_file()
    assert (middleware / "usage_projection_middleware.py").is_file()
    assert (middleware / "session_title_middleware.py").is_file()


def test_prompt_specs_are_versioned_and_render_inputs_separately() -> None:
    assert QUESTION_CURATION_PROMPT.id == "question-curation"
    assert QUESTION_CURATION_PROMPT.version == "1.0"
    assert SINGLE_REVIEW_EVALUATION_PROMPT.id == "single-review-answer-evaluation"

    curation_input = render_question_curation_input(
        ("来源正文",),
        known_questions=("已有题目",),
        rewrite_feedback="补充边界",
    )
    assert curation_input == (
        "来源：\n来源正文\n现有相似题：\n已有题目\n重写要求：\n补充边界"
    )
    evaluation_input = render_single_evaluation_input(
        question="什么是 ACID？",
        reference_answer="四个特性",
        key_points=("原子性", "一致性"),
        user_answer="包含原子性",
    )
    assert "关键点：原子性, 一致性" in evaluation_input
    assert "用户回答：包含原子性" in evaluation_input


@pytest.mark.parametrize(
    ("field", "value"),
    (("id", ""), ("version", ""), ("system", "")),
)
def test_prompt_spec_rejects_missing_identity(field: str, value: str) -> None:
    values = {"id": "prompt", "version": "1.0", "system": "instruction"}
    values[field] = value
    with pytest.raises(ValueError):
        PromptSpec(**values)


def test_isolated_thread_config_preserves_non_configurable_options(tmp_path: Path) -> None:
    context = AgentContext(
        workspace_id="workspace",
        workspace_root=tmp_path,
        session_id="session",
        run_id="run",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    assert isolated_thread_config(
        {
            "configurable": {"thread_id": "outer"},
            "recursion_limit": 20,
        },
        context,
        "answer_evaluation",
    ) == {
        "configurable": {
            "thread_id": "session:answer_evaluation",
        },
        "recursion_limit": 20,
    }
