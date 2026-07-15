from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec


class CandidateSelector(BaseModel):
    scope: Literal["none", "explicit", "recommended", "noted", "unnoted", "all"] = "none"
    ordinals: list[int] = Field(default_factory=list)


class CurationIntentPlan(BaseModel):
    publish: CandidateSelector = Field(default_factory=CandidateSelector)
    reject: CandidateSelector = Field(default_factory=CandidateSelector)
    regenerate: CandidateSelector = Field(default_factory=CandidateSelector)
    inspect: CandidateSelector = Field(default_factory=CandidateSelector)
    feedback: str = ""
    resummarize: bool = False
    clarification: str = ""
    response: str = ""


class AgentRunnable(Protocol):
    async def ainvoke(self, input: dict[str, Any], config=None, *, context=None) -> dict[str, Any]: ...


_PROMPT = """你是题库整理会话的意图识别 Agent。用户可以自由表达发布、拒绝、重新生成、重新总结，也可以询问某道候选题的内容。
只输出结构化计划，不得执行发布。候选题必须用给定序号选择；不要编造序号。
“加了备注的重新生成，其他的发布”应识别为 regenerate=noted、publish=unnoted。
解析“这题”“它”“刚才那题”等指代时，必须结合最近对话和最近关联候选；例如上一轮查看第 6 题，下一轮说“这题发布吧”，应识别为 publish explicit [6]。
用户询问“第几题怎么写的”或要求查看题目内容时，只设置 inspect selector；具体回答由领域服务根据候选事实生成。
只有不属于候选题查看、但可以基于上下文直接回答的普通问题，才把回答写入 response。
无法安全确定意图时，把原因和需要用户补充的内容写入 clarification，其他操作保持 none。"""


@dataclass(frozen=True, slots=True)
class CurationIntentAgent:
    runnable: AgentRunnable

    @classmethod
    def create(cls, factory: AgentFactory, *, model_bindings, middleware=()):
        return cls(factory.create(AgentSpec(role="question_generation", system_prompt=_PROMPT, middleware=tuple(middleware), response_format=CurationIntentPlan), model_bindings=model_bindings))

    async def resolve(
        self,
        *,
        text: str,
        candidates: tuple[dict[str, Any], ...],
        context: AgentContext,
        conversation: tuple[dict[str, Any], ...] = (),
    ) -> CurationIntentPlan:
        lines = ["最近对话："]
        if conversation:
            for message in conversation:
                ordinals = message.get("candidateOrdinals") or ()
                focus = (
                    f" [关联候选: {', '.join(f'第{value}题' for value in ordinals)}]"
                    if ordinals
                    else ""
                )
                lines.append(
                    f"{message.get('role', 'unknown')}{focus}: {message.get('content', '')}"
                )
        else:
            lines.append("（无）")
        lines.extend([f"当前用户输入：{text}", "当前候选题："])
        for item in candidates:
            note = str(
                item.get("review_note") or item.get("reviewNote") or ""
            ).strip()
            question = item.get("question") or {}
            key_points = "、".join(question.get("key_points") or [])
            follow_ups = "、".join(question.get("follow_ups") or [])
            lines.append(
                f"{item['ordinal']}. {item['title']}；题目={question.get('question_text', '')}；"
                f"参考答案={question.get('reference_answer', '')}；关键点={key_points}；"
                f"必要追问={follow_ups}；建议={item.get('recommendation')}；"
                f"备注={'有' if note else '无'}；状态={item.get('status', 'review_pending')}"
            )
        result = await self.runnable.ainvoke({"messages": [HumanMessage(content="\n".join(lines))]}, {"configurable": {"thread_id": f"{context.session_id}:curation_intent"}}, context=context)
        return CurationIntentPlan.model_validate(result["structured_response"])
