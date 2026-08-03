from __future__ import annotations

import json
import re

from app.agents.prompts.prompt_spec import PromptSpec
from app.graphs.interview_retrospective_cleanup import create_source_units


RETROSPECTIVE_CLEANUP_PROMPT = PromptSpec(
    id="interview_retrospective.cleanup",
    version="2026-08-02-clean-transcript-target-v1",
    system=(
        "你是面试 ASR 准确转写整理节点。程序给出 beforeContext、targetText 和 afterContext；"
        "你只拥有 targetText，前后文只用于理解，绝不能复制到 correctedTarget。"
        "correctedTarget 必须完整覆盖 targetText 的原意与事实顺序：修复明显错字、ASR 技术术语、"
        "断句和标点，删除不承载语义的口头禅及紧邻重复词；在上下文足够明确时，可用"
        "“面试官：”“候选人：”整理说话人，但不得为了形成完整问答而补写录音中不存在的话。"
        "不得总结、遗漏事实、补充事实、调整内容顺序、"
        "改变表达立场或将了解、参与、负责、设计、主导等职责等级相互替换。"
        "uncertainItems 不是低置信词清单，只能放入会改变正文且需要用户作决定的少量问题："
        "excerpt 必须是 correctedTarget 中只出现一次的连续原文；术语问题必须同时提供与 excerpt "
        "不同的 possibleValue。正常但无法百分之百确认的技术词、没有明确替代值的词、"
        "possibleValue 与 excerpt 相同的项不得上报；无法唯一定位的疑点只保留在模型内部，不得上报。"
        "说话人或语义确实影响归属、否定、数字、时间、主体、组织名称、职责等级或技术结论时，"
        "必须保留原文并放入 uncertainItems；每个窗口最多返回 8 项。"
        "否定、数字、时间、主体、组织名称和技术结论没有充分证据时必须保留原文。"
        "只可参考 terminologyHints，不得使用标准答案、画像评价、历史结论或联网知识。"
        "recordingCoverage=candidate_only 时不得把反推问题写成录音原话；缺失问题由后续问题还原节点"
        "基于已确认回答生成 inferred question。recollection 不得伪装成逐字转写。"
        "不得补写缺失对话、总结表现或调用工具。只返回 correctedTarget 与必要的少量 uncertainItems；"
        "不得返回 sourceUnits、turns、offset、segments、corrections 或 Diff。"
    ),
)


RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT = PromptSpec(
    id="interview_retrospective.question_extraction",
    version="2026-08-03-transcript-only-v2",
    system=(
        "你是面试问题还原 Agent。只能使用输入中的已确认说话人片段，按面试发生顺序"
        "提取问题并关联回答片段。原文明确出现的问题标为 original；只有回答明确暗示"
        "存在某个问题时才可标为 inferred，并给出 inferenceBasis。不得把建议、总结或"
        "常识补充伪装成面试原问题，不得调用工具或输出整场评分。"
        "只返回问题语义和证据片段；ordinal、anchorSegmentId、全局排序与跨窗口合并由程序计算，"
        "不得自行生成。questionKind 无法可靠分类时使用 unknown。"
        "窗口开头若明显承接上一窗口问题，标记 boundaryRelation=continues_previous；无法判断"
        "则标记 uncertain。recordingCoverage=candidate_only 时，应根据回答中的对象、论证方向、"
        "承接词和答题结构恢复能够被证据直接支持的问题；问题文字采用保守概括，origin 必须为 inferred，"
        "questionSegmentIds 必须为空，answerSegmentIds 和 inferenceBasis 必须说明依据，不得伪造"
        "面试官原话。只能引用当前窗口提供的片段 ID。"
    ),
)


RETROSPECTIVE_ANALYSIS_PROMPT = PromptSpec(
    id="interview_retrospective.question_analysis",
    version="2026-08-02",
    system=(
        "你是逐题面试复盘 Agent。只分析当前问题、关联回答片段和冻结的有限上下文。"
        "明确区分原始证据、画像冲突、模型判断和证据不足；所有优点、改进和缺口尽量"
        "绑定证据片段。不得输出思维过程、整场总分、费用或未经证实的事实，不得调用"
        "工具或修改题库、画像、项目资料与 Knowledge。"
    ),
)


RETROSPECTIVE_CHAT_PROMPT = PromptSpec(
    id="interview_retrospective.chat",
    version="2026-08-02",
    system=(
        "你是面试复盘讨论助手。你只能通过获准的只读工具查看当前复盘、当前求职目标、"
        "已确认画像、正式题库和已发布 Knowledge；不得读取其他复盘，不得接收 Workspace "
        "或复盘 ID 参数，不得直接写任何业务资料。普通追问返回 explanation。若用户明确指出"
        "题目文字、片段归属、说话人或分析结论需要修改，只返回一种结构化纠正建议，准确填写"
        "before、after 与 rationale；建议不会自动生效，必须等待用户确认。"
    ),
)


def render_chat_input(
    *,
    message: str,
    selected_question_id: str | None,
    conversation: list[dict[str, str]],
) -> str:
    return json.dumps(
        {
            "message": message,
            "selectedQuestionId": selected_question_id,
            "recentConversation": conversation[-12:],
        },
        ensure_ascii=False,
        indent=2,
    )


def render_cleanup_window(
    *,
    source_kind: str,
    recording_coverage: str = "mixed_unknown",
    source_start: int,
    source_end: int,
    emit_start: int | None = None,
    body: str,
    speaker_hints: tuple[dict[str, str], ...] = (),
    terminology_hints: tuple[str, ...] = (),
) -> str:
    effective_emit_start = source_start if emit_start is None else emit_start
    source_units = create_source_units(
        body,
        source_start=source_start,
        source_end=source_end,
        emit_start=effective_emit_start,
    )
    return json.dumps(
        {
            "sourceKind": source_kind,
            "recordingCoverage": recording_coverage,
            "sourceStart": source_start,
            "sourceEnd": source_end,
            "emitFrom": effective_emit_start,
            "speakerHints": speaker_hints,
            "terminologyHints": terminology_hints,
            "sourceUnits": [unit.as_prompt_dict() for unit in source_units],
        },
        ensure_ascii=False,
        indent=2,
    )


def render_cleanup_target_window(
    *,
    source_kind: str,
    recording_coverage: str,
    target_start: int,
    target_end: int,
    before_context: str,
    target_text: str,
    after_context: str,
    terminology_hints: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "sourceKind": source_kind,
            "recordingCoverage": recording_coverage,
            "targetStart": target_start,
            "targetEnd": target_end,
            "beforeContext": before_context,
            "targetText": target_text,
            "afterContext": after_context,
            "terminologyHints": list(terminology_hints),
        },
        ensure_ascii=False,
        indent=2,
    )


def render_question_extraction_input(
    *,
    segments: list[dict[str, object]],
    recording_coverage: str = "mixed_unknown",
) -> str:
    return json.dumps(
        {
            "contextScope": "transcript_only",
            "recordingCoverage": recording_coverage,
            "segments": segments,
        },
        ensure_ascii=False,
        indent=2,
    )


def render_question_extraction_repair_input(
    *,
    invalid_output: dict[str, object],
    validation_error: str,
    evidence_segments: list[dict[str, object]],
    recording_coverage: str,
) -> str:
    return json.dumps(
        {
            "task": "repair_question_extraction_output",
            "contextScope": "referenced_evidence_only",
            "recordingCoverage": recording_coverage,
            "validationError": validation_error[:800],
            "invalidOutput": invalid_output,
            "evidenceSegments": evidence_segments,
            "instruction": (
                "只修复 invalidOutput 的结构和缺失语义字段；不得新增没有证据的问题。"
                "仅可引用 evidenceSegments 中的 ID。"
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def render_question_analysis_input(
    *,
    question: dict[str, object],
    segments: list[dict[str, object]],
    context_snapshot: dict[str, object],
) -> str:
    bounded_context = _question_analysis_context(
        context_snapshot=context_snapshot,
        question=question,
        segments=segments,
    )
    return json.dumps(
        {
            "contextSnapshot": bounded_context,
            "question": question,
            "segments": segments,
        },
        ensure_ascii=False,
        indent=2,
    )


def _question_analysis_context(
    *,
    context_snapshot: dict[str, object],
    question: dict[str, object],
    segments: list[dict[str, object]],
) -> dict[str, object]:
    target = context_snapshot.get("target")
    bounded_target: dict[str, object] = {}
    if isinstance(target, dict):
        for key in ("id", "companyName", "roleName", "seniority"):
            value = target.get(key)
            if value is not None:
                bounded_target[key] = value

    query_parts = [str(question.get("questionText") or "")]
    query_parts.extend(str(segment.get("body") or "") for segment in segments)
    query_terms = _analysis_search_terms("\n".join(query_parts))
    profile = context_snapshot.get("profile")
    candidates: list[tuple[int, int, dict[str, object]]] = []
    if isinstance(profile, dict):
        items = profile.get("items")
        if isinstance(items, list):
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                value_text = json.dumps(value, ensure_ascii=False, sort_keys=True)
                score = len(query_terms & _analysis_search_terms(value_text))
                if score <= 0:
                    continue
                candidates.append((score, index, item))

    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    profile_evidence: list[dict[str, object]] = []
    evidence_characters = 0
    for _score, _index, item in candidates:
        compact = {
            key: item[key]
            for key in (
                "claimId",
                "claimVersionId",
                "claimType",
                "supportStatus",
                "value",
            )
            if key in item
        }
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        if len(encoded) > 2_400 or evidence_characters + len(encoded) > 8_000:
            continue
        profile_evidence.append(compact)
        evidence_characters += len(encoded)
        if len(profile_evidence) >= 6:
            break

    return {
        "target": bounded_target,
        "profileVersion": profile.get("version") if isinstance(profile, dict) else None,
        "profileEvidence": profile_evidence,
    }


def _analysis_search_terms(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value.casefold())
    terms = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
    }
    terms.update(
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}", value.casefold())
    )
    return terms
