from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol, Sequence, TypedDict
from uuid import NAMESPACE_URL, uuid5

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import StreamWriter, interrupt

from app.agents.context import AgentContext
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.review.models import ReviewAttemptRecord
from app.review.coverage import (
    KeyPointCoverage,
    ReviewCompletionPolicy,
    merge_key_point_coverage,
)
from app.review.repository import ReviewRepository


@dataclass(frozen=True, slots=True)
class DraftRef:
    id: str
    version: int
    content_hash: str
    report_kind: Literal["session_report", "mastery_report"]


class ReviewRoundState(TypedDict, total=False):
    round_id: str
    settings: dict
    question_snapshots: list[dict]
    current_index: int
    current_input_request: dict
    current_answer: str
    current_evaluation: dict
    current_follow_up: str
    follow_up_skipped: bool
    skipped: bool
    attempt_ids: list[str]
    report_draft_ids: list[str]
    report_drafts: list[dict]
    publication_action_ids: list[str]
    publication_index: int
    publication_decisions: list[dict]
    status: str
    attempt_status: str
    response: str


class RoundAgents(Protocol):
    async def evaluate(self, **kwargs: Any) -> RoundAnswerEvaluation: ...

    async def report(self, **kwargs: Any) -> ReviewSessionReportOutput: ...


DraftCreator = Callable[..., Awaitable[Sequence[DraftRef]]]
ActionRequester = Callable[[DraftRef], Awaitable[Any]]


def _attempt_payload(attempt: ReviewAttemptRecord) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "ordinal": attempt.ordinal,
        "questionId": attempt.question_snapshot.question_id,
        "answer": attempt.answer,
        "followUpAnswer": attempt.follow_up_answer,
        "evaluation": attempt.evaluation,
        "masterySuggestion": attempt.mastery_suggestion,
        "skipped": attempt.skipped,
        "coverage": [asdict(item) for item in attempt.coverage],
        "resultKind": attempt.result_kind,
    }


def create_review_round_graph(
    agents: RoundAgents,
    *,
    repository: ReviewRepository,
    create_report_drafts: DraftCreator,
    request_publication_action: ActionRequester,
    checkpointer=None,
):
    async def load_round(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        return {
            "settings": asdict(round_record.settings),
            "question_snapshots": [
                asdict(question) for question in round_record.question_snapshots
            ],
            "current_index": round_record.current_index,
            "attempt_ids": [
                attempt.id for attempt in repository.list_attempts(round_record.id)
            ],
            "status": round_record.status,
        }

    async def request_answer(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        question = round_record.question_snapshots[state["current_index"]]
        version = state["current_index"] * 2 + 1
        request = repository.ensure_input_request(
            round_id=round_record.id,
            ordinal=state["current_index"] + 1,
            kind="answer",
            prompt=question.question_text,
            version=version,
        )
        value = interrupt(
            {
                "inputRequestId": request.id,
                "kind": request.kind,
                "version": request.version,
                "ordinal": request.ordinal,
            }
        )
        if value.get("inputRequestId") != request.id:
            raise ValueError("resume input request does not match checkpoint")
        return {
            "current_input_request": asdict(request),
            "current_answer": str(value["value"]),
            "skipped": value.get("operation") == "skip",
            "status": "running",
        }

    def after_answer(state: ReviewRoundState) -> str:
        return "persist_attempt" if state.get("skipped") else "evaluate_answer"

    def follow_up_was_skipped(state: ReviewRoundState) -> bool:
        if state.get("follow_up_skipped"):
            return True
        request = state.get("current_input_request", {})
        if request.get("kind") != "follow_up" or not request.get("id"):
            return False
        receipt = repository.get_input_receipt(str(request["id"]))
        return bool(receipt and receipt.receipt.get("operation") == "skip")

    async def evaluate_answer(
        state: ReviewRoundState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
        writer: StreamWriter,
    ) -> dict[str, Any]:
        if follow_up_was_skipped(state):
            return {
                "current_evaluation": state["current_evaluation"],
                "follow_up_skipped": True,
            }
        round_record = repository.get_round(state["round_id"])
        question = round_record.question_snapshots[state["current_index"]]
        attempt = next(
            item
            for item in repository.list_attempts(round_record.id)
            if item.ordinal == state["current_index"] + 1
        )
        writer(
            {
                "type": "review.evaluation.checking_key_points",
                "payload": {
                    "roundId": round_record.id,
                    "attemptId": attempt.id,
                    "ordinal": state["current_index"] + 1,
                },
            }
        )
        evaluation = await agents.evaluate(
            question=question,
            answer=state["current_answer"],
            supplement=state.get("current_follow_up"),
            context=runtime.context,
            config=dict(config),
            progress_scope=(
                round_record.id,
                str(state["current_index"] + 1),
                str(state.get("current_input_request", {}).get("id", "")),
            ),
        )
        writer(
            {
                "type": "review.evaluation.deciding_follow_up",
                "payload": {
                    "roundId": round_record.id,
                    "attemptId": attempt.id,
                    "ordinal": state["current_index"] + 1,
                },
            }
        )
        return {"current_evaluation": evaluation.model_dump()}

    async def request_follow_up(state: ReviewRoundState) -> dict[str, Any]:
        evaluation = RoundAnswerEvaluation.model_validate(
            state["current_evaluation"]
        )
        attempt = next(
            item
            for item in repository.list_attempts(state["round_id"])
            if item.ordinal == state["current_index"] + 1
        )
        missing = [
            item.point for item in attempt.coverage if item.status != "covered"
        ]
        prompt = evaluation.follow_up_prompt or (
            f"请继续补充：{'、'.join(missing)}" if missing else "请继续补充回答"
        )
        version = int(state.get("current_input_request", {}).get("version", 0)) + 1
        request = repository.ensure_input_request(
            round_id=state["round_id"],
            ordinal=state["current_index"] + 1,
            kind="follow_up",
            prompt=prompt,
            version=version,
        )
        value = interrupt(
            {
                "inputRequestId": request.id,
                "kind": request.kind,
                "version": request.version,
                "ordinal": request.ordinal,
            }
        )
        if value.get("inputRequestId") != request.id:
            raise ValueError("resume input request does not match checkpoint")
        return {
            "current_input_request": asdict(request),
            "current_follow_up": str(value["value"]),
            "follow_up_skipped": value.get("operation") == "skip",
        }

    def after_follow_up(state: ReviewRoundState) -> str:
        return "persist_attempt" if state.get("follow_up_skipped") else "evaluate_answer"

    async def persist_attempt(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        ordinal = state["current_index"] + 1
        skipped = bool(state.get("skipped"))
        evaluation = (
            None
            if skipped
            else RoundAnswerEvaluation.model_validate(
                state["current_evaluation"]
            )
        )
        if skipped:
            identifier = str(
                uuid5(NAMESPACE_URL, f"review-attempt:{round_record.id}:{ordinal}")
            )
            attempt_id = repository.save_attempt(
                round_id=round_record.id,
                ordinal=ordinal,
                question_snapshot=round_record.question_snapshots[
                    state["current_index"]
                ],
                answer=state["current_answer"],
                follow_up_answer=None,
                evaluation=None,
                mastery_suggestion=None,
                skipped=True,
                attempt_id=identifier,
            )
            attempt_status = "completed"
        elif follow_up_was_skipped(state):
            attempt = next(
                item
                for item in repository.list_attempts(round_record.id)
                if item.ordinal == ordinal
            )
            completed = repository.skip_attempt(attempt.id)
            attempt_id = completed.id
            attempt_status = completed.status
        else:
            attempt = next(
                item
                for item in repository.list_attempts(round_record.id)
                if item.ordinal == ordinal
            )
            question = attempt.question_snapshot
            coverage = merge_key_point_coverage(
                question.required_key_points,
                attempt.coverage,
                _coverage_decisions(question.required_key_points, evaluation),
            )
            can_advance = ReviewCompletionPolicy.can_advance(
                coverage, skipped=False
            )
            hint_level, revealed = repository.question_assistance(
                round_record.id, ordinal
            )
            result_kind = (
                (
                    "revealed"
                    if revealed
                    else "assisted_mastery"
                    if hint_level > 0
                    else "independent_mastery"
                )
                if can_advance
                else None
            )
            completed = repository.complete_attempt_evaluation(
                attempt.id,
                evaluation=evaluation.model_dump(),
                mastery_suggestion=evaluation.mastery_suggestion,
                needs_follow_up=not can_advance,
                coverage=coverage,
                result_kind=result_kind,
                hint_level=hint_level,
            )
            attempt_id = completed.id
            attempt_status = completed.status
        attempt_ids = list(state.get("attempt_ids", []))
        if attempt_id not in attempt_ids:
            attempt_ids.append(attempt_id)
        return {
            "attempt_ids": attempt_ids,
            "attempt_status": attempt_status,
        }

    def after_persist_attempt(state: ReviewRoundState) -> str:
        return (
            "request_follow_up"
            if state.get("attempt_status") == "waiting_for_follow_up"
            else "advance"
        )

    async def advance(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        next_index = state["current_index"] + 1
        status = (
            "report_pending"
            if next_index >= len(round_record.question_snapshots)
            else "waiting_for_input"
        )
        repository.advance_round(
            round_record.id,
            expected_version=round_record.version,
            current_index=next_index,
            status=status,
        )
        return {
            "current_index": next_index,
            "current_input_request": {},
            "current_answer": "",
            "current_evaluation": {},
            "current_follow_up": "",
            "follow_up_skipped": False,
            "skipped": False,
            "attempt_status": "",
            "status": status,
        }

    def after_advance(state: ReviewRoundState) -> str:
        if state["status"] == "report_pending":
            return "generate_reports"
        return "request_answer"

    async def generate_reports(
        state: ReviewRoundState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        attempts = repository.list_attempts(round_record.id)
        report = await agents.report(
            attempts=tuple(_attempt_payload(attempt) for attempt in attempts),
            settings=asdict(round_record.settings),
            prior_reports=(),
            context=runtime.context,
            config=dict(config),
        )
        return {"response": report.model_dump()}

    async def save_report_drafts(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        attempts = repository.list_attempts(round_record.id)
        report = ReviewSessionReportOutput.model_validate(state["response"])
        drafts = tuple(
            await create_report_drafts(
                round_record=round_record,
                attempts=attempts,
                report=report,
            )
        )
        return {
            "report_draft_ids": [draft.id for draft in drafts],
            "report_drafts": [asdict(draft) for draft in drafts],
            "publication_action_ids": [],
            "publication_index": 0,
            "publication_decisions": [],
        }

    async def prepare_publication(state: ReviewRoundState) -> dict[str, Any]:
        draft = DraftRef(**state["report_drafts"][state["publication_index"]])
        action = await request_publication_action(draft)
        return {
            "publication_action_ids": [
                *state.get("publication_action_ids", []),
                action.id,
            ]
        }

    async def await_publication(state: ReviewRoundState) -> dict[str, Any]:
        index = state["publication_index"]
        action_id = state["publication_action_ids"][index]
        decision = interrupt({"actionId": action_id})
        return {
            "publication_index": index + 1,
            "publication_decisions": [
                *state.get("publication_decisions", []),
                dict(decision),
            ],
        }

    def after_publication(state: ReviewRoundState) -> str:
        if state["publication_index"] < len(state["report_drafts"]):
            return "prepare_publication"
        return "finish"

    async def finish(state: ReviewRoundState) -> dict[str, Any]:
        round_record = repository.get_round(state["round_id"])
        if round_record.status != "completed":
            repository.advance_round(
                round_record.id,
                expected_version=round_record.version,
                current_index=round_record.current_index,
                status="completed",
            )
        return {"status": "completed"}

    graph = StateGraph(ReviewRoundState, context_schema=AgentContext)
    graph.add_node("load_round", load_round)
    graph.add_node("request_answer", request_answer)
    graph.add_node("evaluate_answer", evaluate_answer)
    graph.add_node("request_follow_up", request_follow_up)
    graph.add_node("persist_attempt", persist_attempt)
    graph.add_node("advance", advance)
    graph.add_node("generate_reports", generate_reports)
    graph.add_node("save_report_drafts", save_report_drafts)
    graph.add_node("prepare_publication", prepare_publication)
    graph.add_node("await_publication", await_publication)
    graph.add_node("finish", finish)
    graph.add_edge(START, "load_round")
    graph.add_edge("load_round", "request_answer")
    graph.add_conditional_edges("request_answer", after_answer)
    graph.add_edge("evaluate_answer", "persist_attempt")
    graph.add_conditional_edges("request_follow_up", after_follow_up)
    graph.add_conditional_edges("persist_attempt", after_persist_attempt)
    graph.add_conditional_edges("advance", after_advance)
    graph.add_edge("generate_reports", "save_report_drafts")
    graph.add_edge("save_report_drafts", "prepare_publication")
    graph.add_edge("prepare_publication", "await_publication")
    graph.add_conditional_edges("await_publication", after_publication)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def _coverage_decisions(
    required_points: tuple[str, ...],
    evaluation: RoundAnswerEvaluation,
) -> tuple[KeyPointCoverage, ...]:
    required = set(required_points)
    explicit = bool(
        evaluation.covered_key_points or evaluation.partial_key_points
    )
    if explicit:
        reported = (
            *evaluation.covered_key_points,
            *evaluation.partial_key_points,
            *evaluation.missing_key_points,
        )
        unknown = [point for point in reported if point not in required]
        if unknown:
            raise ValueError(f"unknown key point in evaluation: {unknown[0]}")
        overlap = (
            set(evaluation.covered_key_points)
            & set(evaluation.partial_key_points)
        ) | (
            set(evaluation.covered_key_points)
            & set(evaluation.missing_key_points)
        ) | (
            set(evaluation.partial_key_points)
            & set(evaluation.missing_key_points)
        )
        if overlap:
            raise ValueError("evaluation returned contradictory key point status")
        status_by_point = {
            **{point: "covered" for point in evaluation.covered_key_points},
            **{point: "partial" for point in evaluation.partial_key_points},
            **{point: "uncovered" for point in evaluation.missing_key_points},
        }
    elif evaluation.score == "good":
        status_by_point = {point: "covered" for point in required_points}
    else:
        matched_missing = {
            point for point in evaluation.missing_key_points if point in required
        }
        status_by_point = {
            point: (
                "uncovered"
                if point in matched_missing
                else "covered" if matched_missing else "partial"
            )
            for point in required_points
        }
    return tuple(
        KeyPointCoverage(
            point=point,
            status=status_by_point.get(point, "uncovered"),  # type: ignore[arg-type]
            evidence=tuple(
                filter(
                    None,
                    (
                        evaluation.evidence_by_point.get(point),
                        (
                            evaluation.evidence
                            if status_by_point.get(point) == "covered"
                            else None
                        ),
                    ),
                )
            ),
        )
        for point in required_points
    )
