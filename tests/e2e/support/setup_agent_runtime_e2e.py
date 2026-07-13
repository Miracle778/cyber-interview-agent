from __future__ import annotations

import json
import time
from pathlib import Path

import httpx


API = "http://127.0.0.1:8017"
WORKSPACE_ROOT = "/private/tmp/cyber-r16-e2e-workspace"
SOURCE = Path("docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md")


def main() -> None:
    with httpx.Client(base_url=API, timeout=10) as client:
        workspace = _ok(
            client.post(
                "/api/settings/workspaces", json={"rootPath": WORKSPACE_ROOT}
            )
        )
        provider = _ok(
            client.post(
                "/api/settings/providers",
                json={
                    "name": "E2E OpenAI",
                    "apiFormat": "openai-compatible",
                    "baseUrl": "http://127.0.0.1:9017/v1",
                    "secretSource": "environment",
                    "secretRef": "R16_E2E_API_KEY",
                },
            )
        )
        model = _ok(
            client.post(
                f"/api/settings/providers/{provider['id']}/models",
                json={"modelId": "e2e-model", "displayName": "E2E Model"},
            )
        )
        _ok(client.post(f"/api/settings/provider-models/{model['id']}/test"))
        _ok(
            client.put(
                f"/api/settings/workspaces/{workspace['id']}/model-bindings",
                json={
                    "bindings": {
                        role: model["id"]
                        for role in (
                            "question_generation",
                            "answer_evaluation",
                            "report_summarization",
                            "agent_chat",
                        )
                    }
                },
            )
        )
        with SOURCE.open("rb") as source:
            _ok(
                client.post(
                    "/api/knowledge/sources",
                    data={"workspaceId": workspace["id"]},
                    files={"file": (SOURCE.name, source, "text/markdown")},
                )
            )
        session = _ok(
            client.post(
                "/api/agent/sessions",
                json={
                    "workspaceId": workspace["id"],
                    "kind": "review.single",
                    "title": "单题复习：Runtime 收敛",
                },
            )
        )
        execution = _ok(
            client.post(
                f"/api/agent/sessions/{session['id']}/executions",
                json={
                    "input": {
                        "question": {
                            "id": "q-runtime",
                            "title": "Runtime 收敛",
                            "questionText": "为什么要收敛 Agent Runtime？",
                            "referenceAnswer": "减少与 LangChain/LangGraph 的重复抽象。",
                            "topics": ["architecture"],
                            "difficulty": "medium",
                            "keyPoints": ["减少重复抽象"],
                            "followUps": [],
                            "mastery": "weak",
                        },
                        "user_answer": "为了减少重复抽象并复用官方 Agent。",
                    }
                },
            )
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            detail = _ok(client.get(f"/api/agent/sessions/{session['id']}"))
            if detail["latestExecution"]["status"] != "running":
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("execution did not settle")
        if detail["latestExecution"]["status"] != "waiting_for_approval":
            raise RuntimeError(f"unexpected status: {detail['latestExecution']['status']}")
        print(
            json.dumps(
                {
                    "workspaceId": workspace["id"],
                    "sessionId": session["id"],
                    "executionId": execution["id"],
                    "actionId": detail["currentAction"]["id"],
                }
            )
        )


def _ok(response: httpx.Response):
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    main()
