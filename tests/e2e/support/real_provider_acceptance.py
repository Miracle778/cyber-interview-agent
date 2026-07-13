from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessageChunk, HumanMessage

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec
from app.agents.model_resolver import ChatModelResolver
from app.agents.review_contracts import AnswerEvaluation
from app.core.app_paths import resolve_app_data_dir
from app.repositories.provider_repository import ProviderRepository
from app.services.secrets import KeyringSecretStore


async def main() -> None:
    database = resolve_app_data_dir() / "app.sqlite"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        workspace = connection.execute(
            "SELECT id, root_path FROM workspaces WHERE available = 1 "
            "AND EXISTS (SELECT 1 FROM workspace_model_bindings b "
            "WHERE b.workspace_id = workspaces.id AND b.role = 'answer_evaluation') "
            "AND EXISTS (SELECT 1 FROM workspace_model_bindings b "
            "WHERE b.workspace_id = workspaces.id AND b.role = 'report_summarization') "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if workspace is None:
            raise RuntimeError("no workspace has both real provider bindings")
        bindings = {
            row["role"]: row["provider_model_id"]
            for row in connection.execute(
                "SELECT role, provider_model_id FROM workspace_model_bindings "
                "WHERE workspace_id = ?",
                (workspace["id"],),
            )
        }
        factory = AgentFactory(
            ChatModelResolver(
                ProviderRepository(connection), {"keyring": KeyringSecretStore()}
            )
        )
        context = AgentContext(
            workspace_id=workspace["id"],
            workspace_root=Path(workspace["root_path"]),
            session_id="real-provider-acceptance",
            run_id="real-provider-acceptance",
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )

        evaluator = factory.create(
            AgentSpec(
                role="answer_evaluation",
                system_prompt="返回结构化评价。",
                response_format=AnswerEvaluation,
            ),
            model_bindings=bindings,
        )
        evaluated = await evaluator.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "问题：Python 生成器的主要价值是什么？\n"
                            "参考答案：惰性计算与节省内存。\n"
                            "用户回答：它按需生成数据并减少内存占用。"
                        )
                    )
                ]
            },
            context=context,
        )
        evaluation = AnswerEvaluation.model_validate(
            evaluated["structured_response"]
        )

        reporter = factory.create(
            AgentSpec(
                role="report_summarization",
                system_prompt="生成两点以内的简短中文复习建议。",
            ),
            model_bindings=bindings,
        )
        chunks = 0
        async for message, _metadata in reporter.astream(
            {"messages": [HumanMessage(content="总结 Python 生成器复习重点。")]},
            context=context,
            stream_mode="messages",
        ):
            if isinstance(message, AIMessageChunk) and message.text:
                chunks += 1
        if chunks < 1:
            raise RuntimeError("anthropic-compatible agent returned no stream chunks")

        evaluation_model = factory.resolve_model(
            "answer_evaluation", model_bindings=bindings
        )
        report_model = factory.resolve_model(
            "report_summarization", model_bindings=bindings
        )
        print(
            json.dumps(
                {
                    "evaluationModel": type(evaluation_model).__name__,
                    "evaluationScore": evaluation.score,
                    "reportModel": type(report_model).__name__,
                    "reportChunks": chunks,
                },
                ensure_ascii=False,
            )
        )
    finally:
        connection.close()


if __name__ == "__main__":
    asyncio.run(main())
