from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any, Protocol

from app.hitl.handlers import ActionPayloadValidationError
from app.hitl.models import PendingActionRecord, ResolutionReceipt
from app.knowledge.drafts import (
    DraftVersionChangedError,
    KnowledgeDraftRecord,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.publication import PublicationService


class EventPublisher(Protocol):
    async def publish(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> object: ...


class KnowledgePublishActionHandler:
    def __init__(
        self,
        *,
        drafts: KnowledgeDraftService,
        publications: PublicationService,
        event_stream: EventPublisher,
    ) -> None:
        self._drafts = drafts
        self._publications = publications
        self._event_stream = event_stream

    def apply_edit(
        self,
        action: PendingActionRecord,
        edited_payload: dict[str, Any],
    ) -> dict[str, Any]:
        disallowed = set(edited_payload) - set(action.editable_fields)
        if disallowed:
            fields = ", ".join(sorted(disallowed))
            raise ActionPayloadValidationError(
                f"fields are not editable for {action.action_type!r}: {fields}"
            )
        title = edited_payload.get("title", action.payload["title"])
        markdown = edited_payload.get("markdown", action.payload["markdown"])
        if not isinstance(title, str) or not title.strip():
            raise ActionPayloadValidationError("title must not be empty")
        if not isinstance(markdown, str) or not markdown.strip():
            raise ActionPayloadValidationError("markdown must not be empty")
        return {**action.payload, "title": title.strip(), "markdown": markdown}

    async def after_resolution(
        self,
        action: PendingActionRecord,
        _receipt: ResolutionReceipt,
    ) -> None:
        if action.status == "rejected":
            return

        effective_action = action
        if action.status == "edited_and_approved":
            draft = await self._apply_approved_edit(action)
            effective_action = replace(
                action,
                payload={
                    **action.payload,
                    "draftVersion": draft.version,
                    "contentHash": draft.content_hash,
                    "title": draft.title,
                    "markdown": draft.markdown,
                },
            )

        await self._event_stream.publish(
            action.session_id,
            action.run_id,
            "publication.started",
            {"actionId": action.id, "draftId": action.payload["draftId"]},
        )
        publication = await self._publications.publish_approved_action(
            effective_action
        )
        event_type = (
            "publication.index_stale"
            if publication.state == "index_stale"
            else "publication.completed"
        )
        await self._event_stream.publish(
            action.session_id,
            action.run_id,
            event_type,
            {
                "actionId": action.id,
                "draftId": publication.draft_id,
                "targetPath": publication.target_path,
                "state": publication.state,
            },
        )

    async def _apply_approved_edit(
        self, action: PendingActionRecord
    ) -> KnowledgeDraftRecord:
        draft_id = str(action.payload["draftId"])
        expected_version = int(action.payload["draftVersion"])
        title = str(action.payload["title"])
        markdown = str(action.payload["markdown"])
        current = await self._drafts.get(draft_id)
        if current.version == expected_version:
            return await self._drafts.update(
                draft_id,
                UpdateDraftCommand(
                    expected_version=expected_version,
                    title=title,
                    markdown=markdown,
                ),
            )

        expected_hash = sha256(markdown.encode("utf-8")).hexdigest()
        if (
            current.version == expected_version + 1
            and current.title == title
            and current.content_hash == expected_hash
        ):
            return current
        raise DraftVersionChangedError(
            f"draft {draft_id!r} changed before approved edit was delivered"
        )
