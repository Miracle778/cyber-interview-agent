from __future__ import annotations

import json
import sys
import time

import httpx


API = "http://127.0.0.1:8017"


def main(session_id: str) -> None:
    with httpx.Client(base_url=API, timeout=15) as client:
        executions = 1
        while executions <= 14:
            detail = _wait_for(client, session_id, {"waiting_for_approval", "failed"})
            if detail["latestExecution"]["status"] == "failed":
                raise RuntimeError("review execution failed during compaction exercise")
            if detail["contextCompacted"]:
                _reject_current(client, detail)
                print(json.dumps({"executions": executions, "contextCompacted": True}))
                return
            _reject_current(client, detail)
            _wait_for(client, session_id, {"completed"})
            executions += 1
            _ok(
                client.post(
                    f"/api/agent/sessions/{session_id}/executions",
                    json={
                        "input": {
                            "question": {
                                "id": "q-compaction",
                                "title": "上下文压缩",
                                "questionText": "何时压缩上下文？",
                                "referenceAnswer": "达到官方消息阈值时。",
                                "topics": ["runtime"],
                                "difficulty": "medium",
                                "keyPoints": ["官方阈值"],
                                "followUps": [],
                                "mastery": "weak",
                            },
                            "user_answer": "达到消息阈值时压缩。",
                        }
                    },
                )
            )
        raise RuntimeError("official summarization threshold was not reached")


def _reject_current(client: httpx.Client, detail: dict) -> None:
    action = detail["currentAction"]
    _ok(
        client.post(
            f"/api/agent/actions/{action['id']}/reject",
            json={
                "version": action["version"],
                "idempotencyKey": f"compaction-{action['id']}",
                "reason": "继续压缩验收",
            },
        )
    )


def _wait_for(
    client: httpx.Client, session_id: str, statuses: set[str]
) -> dict:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        detail = _ok(client.get(f"/api/agent/sessions/{session_id}"))
        if detail["latestExecution"]["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise RuntimeError(f"execution did not reach {sorted(statuses)}")


def _ok(response: httpx.Response):
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    main(sys.argv[1])
