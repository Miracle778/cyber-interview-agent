from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


BASE_URL = os.getenv("R2_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8012")
WORKSPACE_ID = os.environ["R2_ACCEPTANCE_WORKSPACE_ID"]
ANSWER_MODEL_ID = os.environ["R2_ACCEPTANCE_ANSWER_MODEL_ID"]
STATE_PATH = Path(
    os.getenv(
        "R2_ACCEPTANCE_STATE_PATH",
        "/private/tmp/r2-real-provider-acceptance.json",
    )
)

SOURCE = """# R2 十题真实验收资料

请逐条整理以下 12 道面试题，不要合并题目。

1. Redis 缓存穿透是什么？答：查询不存在的数据导致缓存不命中，可用空值缓存和布隆过滤器治理。
2. Redis 缓存击穿是什么？答：热点 key 失效后并发请求打到数据库，可用互斥锁和逻辑过期。
3. Redis 缓存雪崩是什么？答：大量 key 同时过期，可使用随机过期时间、限流和多级缓存。
4. MySQL MVCC 如何工作？答：通过版本链、Read View 和事务 ID 判断记录可见性。
5. MySQL 索引为什么使用 B+ 树？答：树高低、范围扫描友好、叶子节点有序且适合磁盘页。
6. 事务隔离级别有哪些？答：读未提交、读已提交、可重复读和串行化。
7. TCP 三次握手的目的是什么？答：确认双方收发能力并同步初始序列号。
8. HTTP/2 相比 HTTP/1.1 有什么变化？答：二进制分帧、多路复用、头部压缩和流优先级。
9. JVM 垃圾回收如何判断对象存活？答：从 GC Roots 做可达性分析。
10. Java 线程池核心参数有哪些？答：核心线程数、最大线程数、存活时间、队列、线程工厂和拒绝策略。
11. 分布式锁需要满足什么性质？答：互斥、超时释放、持有者校验、续期和故障安全。
12. 消息队列如何保证消费幂等？答：业务幂等键、去重表、状态机和唯一约束。
"""


def _load() -> dict[str, Any]:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save(value: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def _json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    response = await client.request(method, path, **kwargs)
    if not response.is_success:
        raise RuntimeError(
            f"{method} {path} failed: {response.status_code} "
            f"{response.text[:500]}"
        )
    return response.json()


async def _poll(get_value, predicate, *, attempts: int = 180):
    last = None
    for _ in range(attempts):
        last = await get_value()
        if predicate(last):
            return last
        await asyncio.sleep(1)
    raise TimeoutError(f"acceptance poll timed out; last={last!r}")


async def _provider_evidence(client: httpx.AsyncClient) -> list[dict[str, str]]:
    providers = await _json(client, "GET", "/api/settings/providers")
    selected = []
    for provider in providers:
        for model in provider["models"]:
            if model["id"] == ANSWER_MODEL_ID or (
                provider["apiFormat"] == "anthropic-compatible"
                and model["connectivityStatus"] == "ok"
            ):
                selected.append(
                    {
                        "apiFormat": provider["apiFormat"],
                        "modelId": model["modelId"],
                        "connectivityStatus": model["connectivityStatus"],
                    }
                )
    return selected


async def _approve_publication(
    client: httpx.AsyncClient, draft_id: str
) -> dict[str, Any]:
    execution = await _json(
        client,
        "POST",
        f"/api/knowledge/drafts/{draft_id}/publish-request",
    )

    async def pending():
        return await _json(
            client,
            "GET",
            "/api/agent/actions",
            params={
                "workspaceId": WORKSPACE_ID,
                "status": "pending",
                "sessionId": execution["sessionId"],
            },
        )

    actions = await _poll(pending, lambda value: len(value) == 1)
    action = actions[0]
    await _json(
        client,
        "POST",
        f"/api/agent/actions/{action['id']}/approve",
        json={
            "version": action["version"],
            "idempotencyKey": f"accept-{uuid4()}",
        },
    )

    async def published():
        return await _json(
            client, "GET", f"/api/knowledge/drafts/{draft_id}"
        )

    return await _poll(
        published,
        lambda value: value["status"] == "published"
        and value["publication"] is not None,
    )


async def prepare() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        upload = await _json(
            client,
            "POST",
            "/api/knowledge/sources",
            data={"workspaceId": WORKSPACE_ID},
            files={
                "file": (
                    "r2-real-acceptance.md",
                    SOURCE.encode(),
                    "text/markdown",
                )
            },
        )
        batch = await _json(
            client,
            "POST",
            "/api/review/question-batches",
            json={
                "workspaceId": WORKSPACE_ID,
                "sourceRefs": [upload["source"]["id"]],
            },
        )

        async def batch_detail():
            return await _json(
                client,
                "GET",
                f"/api/review/question-batches/{batch['id']}",
            )

        batch = await _poll(
            batch_detail,
            lambda value: value["status"] in {"completed", "failed"},
        )
        if batch["status"] != "completed":
            raise RuntimeError("question curation failed")
        if batch["candidateCount"] < 10:
            raise RuntimeError(
                f"provider generated only {batch['candidateCount']} candidates"
            )

        published_paths = []
        for candidate in batch["candidates"][:12]:
            draft = await _approve_publication(client, candidate["draft"]["id"])
            published_paths.append(draft["publication"]["targetPath"])

        questions = await _poll(
            lambda: _json(
                client,
                "GET",
                "/api/review/questions",
                params={"workspaceId": WORKSPACE_ID},
            ),
            lambda value: len(value) >= 10,
        )
        round_value = await _json(
            client,
            "POST",
            "/api/review/rounds",
            json={
                "workspaceId": WORKSPACE_ID,
                "selectedTopics": [],
                "difficulties": ["easy", "medium", "hard"],
                "mode": "random-mixed",
                "questionCount": 10,
                "allowFollowUp": True,
                "seed": 20260714,
                "answerModelId": ANSWER_MODEL_ID,
                "reasoningEffort": "none",
            },
        )
        if round_value["status"] != "waiting_for_input":
            raise RuntimeError("round did not stop for the first answer")
        state = {
            "workspaceId": WORKSPACE_ID,
            "batchId": batch["id"],
            "roundId": round_value["id"],
            "sessionId": round_value["sessionId"],
            "executionId": round_value["executionId"],
            "providers": await _provider_evidence(client),
            "candidateCount": batch["candidateCount"],
            "activeQuestionCount": len(questions),
            "questionPublicationCount": len(published_paths),
        }
        _save(state)
        print(json.dumps(state, ensure_ascii=False))


async def complete() -> None:
    state = _load()
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        round_value = await _json(
            client, "GET", f"/api/review/rounds/{state['roundId']}"
        )
        follow_up_count = 0
        skipped = False
        while round_value["status"] in {"waiting_for_input", "running"}:
            current_input = round_value["currentInput"]
            if current_input is None:
                await asyncio.sleep(1)
                round_value = await _json(
                    client,
                    "GET",
                    f"/api/review/rounds/{state['roundId']}",
                )
                continue
            if current_input["kind"] == "follow_up":
                follow_up_count += 1
                answer = "补充回答：需要结合边界条件、失败恢复和幂等约束。"
            elif current_input["ordinal"] == 2 and not skipped:
                round_value = await _json(
                    client,
                    "POST",
                    f"/api/review/rounds/{state['roundId']}/skip",
                    json={
                        "inputRequestId": current_input["id"],
                        "version": current_input["version"],
                        "idempotencyKey": f"skip-{uuid4()}",
                    },
                )
                skipped = True
                continue
            else:
                answer = (
                    "我先给出核心定义和主要机制，并说明常见治理方式；"
                    "若细节不足请继续追问。"
                )
            round_value = await _json(
                client,
                "POST",
                f"/api/review/rounds/{state['roundId']}/answers",
                json={
                    "inputRequestId": current_input["id"],
                    "version": current_input["version"],
                    "idempotencyKey": f"answer-{uuid4()}",
                    "value": answer,
                },
            )

        if round_value["status"] != "report_pending":
            raise RuntimeError(f"unexpected final round status {round_value['status']}")
        if len(round_value["attempts"]) != 10:
            raise RuntimeError("ten-question round did not persist ten attempts")
        state.update(
            {
                "followUpCount": follow_up_count,
                "skippedCount": sum(
                    item["skipped"] for item in round_value["attempts"]
                ),
                "usageBeforeApproval": round_value["usage"],
                "reportPending": True,
            }
        )
        _save(state)
        print(json.dumps(state, ensure_ascii=False))


async def approve_and_verify() -> None:
    state = _load()
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        round_value = await _json(
            client, "GET", f"/api/review/rounds/{state['roundId']}"
        )
        published = []
        for _ in range(2):
            async def pending():
                return await _json(
                    client,
                    "GET",
                    "/api/agent/actions",
                    params={
                        "workspaceId": WORKSPACE_ID,
                        "status": "pending",
                        "sessionId": state["sessionId"],
                    },
                )

            actions = await _poll(pending, lambda value: len(value) == 1)
            action = actions[0]
            await _json(
                client,
                "POST",
                f"/api/agent/actions/{action['id']}/approve",
                json={
                    "version": action["version"],
                    "idempotencyKey": f"report-{uuid4()}",
                },
            )
            round_value = await _poll(
                lambda: _json(
                    client,
                    "GET",
                    f"/api/review/rounds/{state['roundId']}",
                ),
                lambda value: value["status"] == "completed"
                or len(value["reports"]) > len(published),
            )
            published = [
                report
                for report in round_value["reports"]
                if report["publication"] is not None
            ]

        round_value = await _poll(
            lambda: _json(
                client,
                "GET",
                f"/api/review/rounds/{state['roundId']}",
            ),
            lambda value: value["status"] == "completed",
        )
        discussion = await _json(
            client,
            "POST",
            f"/api/review/rounds/{state['roundId']}/discussions",
            json={
                "ordinal": 1,
                "message": "请解释遗漏点并给出一个迁移应用例子。",
            },
        )
        parent_after = await _json(
            client, "GET", f"/api/review/rounds/{state['roundId']}"
        )
        next_round = await _json(
            client,
            "POST",
            "/api/review/rounds",
            json={
                "workspaceId": WORKSPACE_ID,
                "selectedTopics": [],
                "difficulties": ["easy", "medium", "hard"],
                "mode": "weak-point",
                "questionCount": 1,
                "allowFollowUp": True,
                "seed": 20260715,
                "answerModelId": ANSWER_MODEL_ID,
                "reasoningEffort": "none",
            },
        )
        await _json(
            client,
            "POST",
            f"/api/review/rounds/{next_round['id']}/cancel",
        )
        session = await _json(
            client, "GET", f"/api/agent/sessions/{state['sessionId']}"
        )
        state.update(
            {
                "completed": round_value["status"] == "completed",
                "reportPaths": [
                    report["publication"]["target_path"]
                    for report in round_value["reports"]
                    if report["publication"] is not None
                ],
                "discussionSessionId": discussion["id"],
                "parentAttemptCountAfterDiscussion": len(
                    parent_after["attempts"]
                ),
                "nextWeakPointQuestionId": next_round["currentQuestion"]["id"],
                "contextCompacted": session["contextCompacted"],
                "finalUsage": round_value["usage"],
            }
        )
        _save(state)
        print(json.dumps(state, ensure_ascii=False))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "complete", "approve"))
    args = parser.parse_args()
    await {"prepare": prepare, "complete": complete, "approve": approve_and_verify}[
        args.phase
    ]()


if __name__ == "__main__":
    asyncio.run(main())
