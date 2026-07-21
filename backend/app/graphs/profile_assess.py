from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.profile_agents import ProfileAgents
from app.agents.profile_contracts import ProfileAssessmentOutput
from app.profile.errors import (
    ProfileAssessmentFailed,
    ProfileClaimVersionConflict,
    ProfileEvidenceMismatch,
)
from app.profile.models import CreateClaimProposalSpec, SaveAssessmentCommand
from app.profile.repository import ProfileRepository


class ProfileAssessState(TypedDict, total=False):
    profile_version: str
    claim_ids: list[str]
    assessment_output: dict[str, Any]
    assessment_id: str
    proposal_ids: list[str]


AssessmentCardProjector = Callable[
    [str, list[str], dict[str, object]], Awaitable[None]
]


def create_profile_assess_graph(
    agents: ProfileAgents,
    *,
    repository: ProfileRepository,
    project_card: AssessmentCardProjector | None,
    checkpointer=None,
):
    async def lock_snapshot(
        _state: ProfileAssessState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        snapshot = repository.profile_snapshot(runtime.context.workspace_id)
        if snapshot.profile_version is None or not snapshot.claims:
            raise ProfileClaimVersionConflict(
                "profile assessment requires a confirmed profile snapshot"
            )
        return {
            "profile_version": snapshot.profile_version,
            "claim_ids": [claim.claim_id for claim in snapshot.claims],
        }

    async def profile_assessment(
        state: ProfileAssessState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        snapshot = repository.profile_snapshot(runtime.context.workspace_id)
        if snapshot.profile_version != state["profile_version"]:
            raise ProfileClaimVersionConflict(
                "profile snapshot changed before assessment"
            )
        model_snapshot = {
            "profileVersion": snapshot.profile_version,
            "claims": [
                {
                    "id": claim.claim_id,
                    "type": claim.claim_type,
                    "claimVersionId": claim.claim_version_id,
                    "versionNumber": claim.version_number,
                    "value": claim.value,
                    "supportStatus": claim.support_status,
                    "evidenceIds": list(claim.evidence_ids),
                }
                for claim in snapshot.claims[:50]
            ],
            "materials": [
                {
                    "id": material.id,
                    "type": material.type,
                    "title": material.title,
                    "currentVersionId": material.current_version_id,
                }
                for material in snapshot.materials[:50]
            ],
        }
        try:
            output = await agents.assess(
                snapshot=model_snapshot,
                context=runtime.context,
                config=dict(config),
            )
        except Exception as error:
            raise ProfileAssessmentFailed(
                "profile assessment model failed"
            ) from error
        return {"assessment_output": output.model_dump(mode="json")}

    async def validate_persist_and_project(
        state: ProfileAssessState,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        current = repository.profile_snapshot(runtime.context.workspace_id)
        if current.profile_version != state["profile_version"]:
            raise ProfileClaimVersionConflict(
                "profile snapshot changed before assessment commit"
            )
        output = ProfileAssessmentOutput.model_validate(
            state["assessment_output"]
        )
        _validate_output_references(
            repository, runtime.context.workspace_id, output
        )
        assessment = repository.save_assessment(
            SaveAssessmentCommand(
                workspace_id=runtime.context.workspace_id,
                base_profile_version=state["profile_version"],
                result=output.model_dump(mode="json"),
                created_by_execution_id=runtime.context.run_id,
            )
        )
        grouped = defaultdict(list)
        for proposal in output.proposal_candidates:
            grouped[proposal.material_version_id].append(
                CreateClaimProposalSpec(
                    proposal_type=proposal.proposal_type,
                    proposed_value=proposal.proposed_value,
                    reason=proposal.reason,
                    evidence_ids=tuple(proposal.evidence_ids),
                    target_claim_id=proposal.target_claim_id,
                    base_claim_version_id=proposal.base_claim_version_id,
                    source="assessment",
                )
            )
        proposal_ids: list[str] = []
        for version_id in sorted(grouped):
            proposals = repository.create_claim_proposals(
                version_id,
                tuple(grouped[version_id]),
                idempotency_key=f"{runtime.context.run_id}:{version_id}",
                created_by_execution_id=runtime.context.run_id,
            )
            proposal_ids.extend(item.id for item in proposals)
        if project_card is not None:
            await project_card(
                assessment.id,
                proposal_ids,
                {
                    "summary": output.summary,
                    "strengthCount": len(output.strengths),
                    "gapCount": len(output.gaps),
                    "riskCount": len(output.risks),
                },
            )
        return {
            "assessment_id": assessment.id,
            "proposal_ids": proposal_ids,
        }

    graph = StateGraph(ProfileAssessState, context_schema=AgentContext)
    graph.add_node("lock_snapshot", lock_snapshot)
    graph.add_node("profile_assessment", profile_assessment)
    graph.add_node("validate_persist_and_project", validate_persist_and_project)
    graph.add_edge(START, "lock_snapshot")
    graph.add_edge("lock_snapshot", "profile_assessment")
    graph.add_edge("profile_assessment", "validate_persist_and_project")
    graph.add_edge("validate_persist_and_project", END)
    return graph.compile(checkpointer=checkpointer)


def _validate_output_references(
    repository: ProfileRepository,
    workspace_id: str,
    output: ProfileAssessmentOutput,
) -> None:
    evidence_rows = repository.connection.execute(
        "SELECT e.id, e.material_version_id FROM profile_evidence e "
        "JOIN profile_material_versions v ON v.id = e.material_version_id "
        "JOIN profile_materials m ON m.id = v.material_id "
        "WHERE m.workspace_id = ? AND m.lifecycle_status = 'active' "
        "AND e.tombstoned_at IS NULL",
        (workspace_id,),
    ).fetchall()
    evidence_versions = {row["id"]: row["material_version_id"] for row in evidence_rows}
    all_references = {
        evidence_id
        for recommendation in output.recommendations
        for evidence_id in recommendation.evidence_ids
    }
    all_references.update(
        evidence_id
        for proposal in output.proposal_candidates
        for evidence_id in proposal.evidence_ids
    )
    if all_references - evidence_versions.keys():
        raise ProfileEvidenceMismatch(
            "profile assessment references unknown Evidence"
        )
    for proposal in output.proposal_candidates:
        if any(
            evidence_versions[evidence_id] != proposal.material_version_id
            for evidence_id in proposal.evidence_ids
        ):
            raise ProfileEvidenceMismatch(
                "assessment proposal Evidence belongs to another material version"
            )
        version = repository.get_material_version(proposal.material_version_id)
        repository.get_material(version.material_id, workspace_id=workspace_id)
        if proposal.proposal_type == "create":
            if (
                proposal.target_claim_id is not None
                or proposal.base_claim_version_id is not None
            ):
                raise ProfileClaimVersionConflict(
                    "assessment create proposal cannot target an existing claim"
                )
            continue
        if proposal.target_claim_id is None:
            raise ProfileClaimVersionConflict(
                "assessment update/reject proposal requires a target claim"
            )
        claim = repository.connection.execute(
            "SELECT workspace_id FROM profile_claims WHERE id = ?",
            (proposal.target_claim_id,),
        ).fetchone()
        if claim is None or claim["workspace_id"] != workspace_id:
            raise ProfileClaimVersionConflict(
                "assessment proposal target is outside the Workspace"
            )
        if proposal.base_claim_version_id is not None:
            base = repository.connection.execute(
                "SELECT claim_id FROM profile_claim_versions WHERE id = ?",
                (proposal.base_claim_version_id,),
            ).fetchone()
            if base is None or base["claim_id"] != proposal.target_claim_id:
                raise ProfileClaimVersionConflict(
                    "assessment proposal base version does not match its Claim"
                )
