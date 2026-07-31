from __future__ import annotations

from app.evaluation.contracts import EvalPack
from app.evaluation.packs.job_analysis import JOB_ANALYSIS_PACK
from app.evaluation.packs.profile import PROFILE_PACK
from app.evaluation.packs.project_deep_dive import PROJECT_DEEP_DIVE_PACK
from app.evaluation.packs.question_curation import (
    QUESTION_CURATION_PACK,
    QUESTION_CURATION_V2_PACK,
)
from app.evaluation.packs.review import REVIEW_PACK


_PACKS = (
    QUESTION_CURATION_PACK,
    QUESTION_CURATION_V2_PACK,
    REVIEW_PACK,
    PROFILE_PACK,
    JOB_ANALYSIS_PACK,
    PROJECT_DEEP_DIVE_PACK,
)

AGENT_EVAL_PACKS: dict[str, EvalPack] = {pack.id: pack for pack in _PACKS}

if len(AGENT_EVAL_PACKS) != len(_PACKS):
    raise RuntimeError("Agent evaluation registry contains duplicate pack IDs")


def get_eval_pack(pack_id: str) -> EvalPack:
    try:
        return AGENT_EVAL_PACKS[pack_id]
    except KeyError as error:
        raise LookupError(f"Eval Pack 不存在: {pack_id}") from error
