from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.review_contracts import (
    AnswerEvaluation,
    SingleReviewInput,
    SingleReviewState,
)
from app.runtime.graph_build_context import GraphBuildContext
from app.runtime.graph_registry import GraphDefinition


def create_single_review_graph(context: GraphBuildContext):
    def review_input(state: SingleReviewState) -> SingleReviewInput:
        return SingleReviewInput.model_validate(
            {
                "question": state["question"],
                "user_answer": state["user_answer"],
            }
        )

    async def evaluate(state: SingleReviewState):
        validated = review_input(state)
        question = validated.question
        evaluation = await context.invoke_model.invoke_structured(
            role="answer_evaluation",
            schema=AnswerEvaluation,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "根据参考答案和关键点评价用户回答。只引用用户回答中的证据，"
                        "返回 poor/partial/good、缺失关键点和简短证据。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{question.question_text}\n"
                        f"参考答案：{question.reference_answer}\n"
                        f"关键点：{', '.join(question.key_points)}\n"
                        f"用户回答：{validated.user_answer}"
                    ),
                },
            ],
        )
        return {"evaluation": evaluation.model_dump()}

    async def create_report(state: SingleReviewState):
        validated = review_input(state)
        chunks: list[str] = []
        async for chunk in context.invoke_model.stream_text(
            role="report_summarization",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "生成简洁的中文单题复习报告 Markdown，包含问题、评分、"
                        "回答证据、缺失点和下一步；不得生成隐藏推理。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{validated.question.question_text}\n"
                        f"用户回答：{validated.user_answer}\n"
                        f"评价：{state['evaluation']}"
                    ),
                },
            ],
        ):
            chunks.append(chunk)
        markdown = "".join(chunks).strip()
        if not markdown:
            raise ValueError("模型未生成复习报告")
        draft = await context.create_draft(
            title=f"单题复习：{validated.question.title}",
            markdown=markdown,
            source_refs=(validated.question.id,),
            relation_refs=tuple(validated.question.topics),
        )
        return {
            "report_markdown": markdown,
            "report_draft_id": draft.id,
            "report_draft_version": draft.version,
            "report_content_hash": draft.content_hash,
        }

    async def request_publication(state: SingleReviewState):
        validated = review_input(state)
        action = await context.request_action(
            action_type="knowledge.publish",
            payload={
                "draftId": state["report_draft_id"],
                "draftVersion": state["report_draft_version"],
                "contentHash": state["report_content_hash"],
                "title": validated.question.title,
                "markdown": state["report_markdown"],
            },
            preview={
                "title": validated.question.title,
                "markdown": state["report_markdown"],
                "draftId": state["report_draft_id"],
                "question": validated.question.model_dump(by_alias=True),
                "evaluation": state["evaluation"],
            },
            editable_fields=("title", "markdown"),
            idempotency_key=(
                f"knowledge.publish:{state['report_draft_id']}:"
                f"{state['report_draft_version']}:{state['report_content_hash']}"
            ),
        )
        decision = interrupt({"actionId": action.id})
        response = (
            "单题复习报告已发布"
            if decision.get("decision") == "approved"
            else f"单题复习报告未发布：{decision.get('reason', '未说明原因')}"
        )
        return {
            "action_id": action.id,
            "decision": decision,
            "response": response,
        }

    graph = StateGraph(SingleReviewState)
    graph.add_node("evaluate_answer", evaluate)
    graph.add_node("create_report", create_report)
    graph.add_node("request_publication", request_publication)
    graph.add_edge(START, "evaluate_answer")
    graph.add_edge("evaluate_answer", "create_report")
    graph.add_edge("create_report", "request_publication")
    graph.add_edge("request_publication", END)
    return graph.compile(checkpointer=context.checkpointer)


def single_review_definition() -> GraphDefinition:
    return GraphDefinition(
        graph_id="review.single",
        graph_version=1,
        factory=create_single_review_graph,
        required_model_roles=frozenset(
            {"answer_evaluation", "report_summarization"}
        ),
        allowed_tools=frozenset(
            {"read_source", "read_active_knowledge", "write_review_draft"}
        ),
        allowed_scopes=frozenset(
            {"review.sources", "review.drafts", "knowledge.active"}
        ),
    )
