from __future__ import annotations

import pytest

from app.knowledge.drafts import KnowledgeDraftService

from interview_retrospective_candidate_helpers import candidate_fixture


@pytest.mark.asyncio
async def test_publication_draft_contains_only_selected_confirmed_fields(tmp_path):
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    connection, app, retrospective, run, _questions = candidate_fixture(
        tmp_path, drafts=drafts
    )
    app.generate_candidates(retrospective.id, run.id)

    draft = await app.create_publication_draft(
        retrospective.id,
        selected_sections=("basic_info", "confirmed_questions", "action_items"),
        idempotency_key="publication-draft",
    )
    replay = await app.create_publication_draft(
        retrospective.id,
        selected_sections=("basic_info", "confirmed_questions", "action_items"),
        idempotency_key="publication-draft",
    )

    assert draft.id == replay.id
    assert draft.document_type == "interview_retrospective"
    assert "如何治理缓存一致性" in draft.markdown
    assert "缓存穿透如何治理" not in draft.markdown
    assert "SECRET_RAW_TRANSCRIPT" not in draft.markdown
    assert "SECRET_PROVIDER_RESPONSE" not in draft.markdown
    assert "SECRET_PROMPT" not in draft.markdown
    connection.close()


def test_retrospective_document_type_uses_dedicated_directory():
    from app.knowledge.document_types import create_document_type_registry

    definition = create_document_type_registry().resolve("interview_retrospective")
    assert definition.path_for("retro-1") == "60_interview_retrospectives/retro-1.md"
