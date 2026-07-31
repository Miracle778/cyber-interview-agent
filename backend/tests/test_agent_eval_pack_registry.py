from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import JudgeResult
from app.evaluation.registry import AGENT_EVAL_PACKS
from app.observability.registry import AGENT_OBSERVABILITY_REGISTRY


def test_eval_pack_ids_versions_and_dimension_ids_are_stable() -> None:
    assert len(AGENT_EVAL_PACKS) == 6
    assert len(AGENT_EVAL_PACKS) == len(set(AGENT_EVAL_PACKS))
    dimension_pairs: set[tuple[str, str]] = set()
    for pack_id, pack in AGENT_EVAL_PACKS.items():
        assert pack.id == pack_id
        assert pack_id.endswith(f".v{pack.version}")
        assert 3 <= len(pack.dimensions) <= 9
        assert len(pack.dimensions) == len(
            {dimension.id for dimension in pack.dimensions}
        )
        if pack.evaluation_contract_version == 1:
            assert pack.required_evidence_event_types
            assert pack.rules
        else:
            assert pack.task_type != "legacy"
            assert pack.judge.response_contract == "JudgeResultV2"
        assert pack.judge.prompt_id.endswith(f".v{pack.version}")
        assert "chain-of-thought" not in pack.judge.instructions.casefold()
        assert "思维链" not in pack.judge.instructions
        dimension_pairs.update(
            (pack_id, dimension.id) for dimension in pack.dimensions
        )
    assert len(dimension_pairs) == sum(
        len(pack.dimensions) for pack in AGENT_EVAL_PACKS.values()
    )

    dimension = next(iter(AGENT_EVAL_PACKS.values())).dimensions[0]
    with pytest.raises(FrozenInstanceError):
        dimension.id = "changed"  # type: ignore[misc]


def test_every_observability_eval_pack_reference_resolves() -> None:
    references = {
        registration.eval_pack_id
        for registration in AGENT_OBSERVABILITY_REGISTRY.values()
        if registration.eval_pack_id is not None
    }
    assert references == set(AGENT_EVAL_PACKS)


def test_judge_result_is_strict_and_requires_cited_hashes() -> None:
    result = JudgeResult.model_validate(
        {
            "dimensions": [
                {
                    "dimensionId": "source_fidelity",
                    "score": 82,
                    "citedEventHashes": ["event-sha"],
                    "citedArtifactHashes": ["artifact-sha"],
                    "confidence": 0.8,
                    "summary": "来源引用可以复核。",
                    "risks": ["一处来源覆盖不足"],
                }
            ],
            "citedEventHashes": ["event-sha"],
            "citedArtifactHashes": ["artifact-sha"],
            "confidence": 0.8,
            "summary": "整体可用。",
            "risks": ["需要人工抽查"],
            "humanReviewRequired": True,
        }
    )
    assert result.dimensions[0].dimension_id == "source_fidelity"
    assert result.human_review_required is True

    with pytest.raises(ValidationError):
        JudgeResult.model_validate(
            {
                **result.model_dump(by_alias=True),
                "hiddenReasoning": "must not be accepted",
            }
        )

    with pytest.raises(ValidationError):
        JudgeResult.model_validate(
            {
                **result.model_dump(by_alias=True),
                "citedEventHashes": [],
                "citedArtifactHashes": [],
            }
        )
