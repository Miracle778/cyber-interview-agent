from __future__ import annotations

import pytest

from app.agents.context_assembly import (
    ContextAssembler,
    ContextBudget,
    ContextBudgetExceededError,
    ContextMaterial,
    ContextMessage,
    ContextResource,
    ContextSummary,
    ContextTurn,
    model_token_counter,
)


def _tokens(text: str) -> int:
    return len(text.split())


def _turn(index: int) -> ContextTurn:
    return ContextTurn(
        messages=(
            ContextMessage(id=f"u{index}", role="user", content="one two"),
            ContextMessage(
                id=f"a{index}", role="assistant", content="three four"
            ),
        )
    )


def test_assembler_reserves_budget_and_keeps_complete_recent_turns() -> None:
    turns = tuple(_turn(index) for index in range(3))

    result = ContextAssembler().assemble(
        ContextMaterial(
            current_input="publish this",
            working_state="state",
            prior_summary=ContextSummary.empty(),
            turns=turns,
            resources=(),
        ),
        ContextBudget(max_input_tokens=24, reserved_output_tokens=4),
        _tokens,
    )

    assert result.recent_turns == turns[-2:]
    assert result.overflow_turns == turns[:1]
    assert result.threshold_tokens == 20
    assert result.estimated_input_tokens == _tokens(result.render())
    assert result.estimated_input_tokens <= result.threshold_tokens


def test_required_resource_over_budget_fails_closed() -> None:
    material = ContextMaterial(
        current_input="publish",
        working_state="state",
        prior_summary=ContextSummary.empty(),
        turns=(),
        resources=(
            ContextResource(
                ref="candidate:1",
                label="full",
                content="x " * 20,
                priority=0,
                required=True,
            ),
        ),
    )

    with pytest.raises(ContextBudgetExceededError) as raised:
        ContextAssembler().assemble(
            material, ContextBudget(max_input_tokens=10), _tokens
        )

    assert str(raised.value) == "context_budget_exceeded"


def test_optional_resources_follow_priority_and_render_only_selected() -> None:
    resources = (
        ContextResource("optional:later", "later", "five six", 20),
        ContextResource("required:focus", "focus", "one two", 0, True),
        ContextResource("optional:first", "first", "three four", 10),
        ContextResource("optional:second", "second", "seven eight", 10),
    )

    result = ContextAssembler().assemble(
        ContextMaterial(
            current_input="publish",
            working_state="state",
            prior_summary=ContextSummary.empty(),
            turns=(),
            resources=resources,
        ),
        ContextBudget(max_input_tokens=19),
        _tokens,
    )

    assert [item.ref for item in result.selected_resources] == [
        "required:focus",
        "optional:first",
        "optional:second",
    ]
    assert "optional:later" not in result.render()


def test_model_token_counter_prefers_provider_and_falls_back() -> None:
    class ProviderCounter:
        def get_num_tokens(self, text: str) -> int:
            return 37

    class BrokenCounter:
        def get_num_tokens(self, text: str) -> int:
            raise RuntimeError("not supported")

    assert model_token_counter(ProviderCounter())("hello") == 37
    assert model_token_counter(BrokenCounter())("hello world") > 0
