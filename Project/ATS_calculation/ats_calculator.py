"""Combine rule-based and LLM ATS scores into the final candidate assessment."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .LLM_based.llm_scorer import (
    extract_numeric_score,
    get_batch_gemini_evaluations,
    get_ollama_evaluation,
    get_ollama_score,
    reset_gemini_failure_state,
)
from .rule_based.rule_based_calculator import (
    ATSFactorResult,
    _clamp,
    _coerce_float,
    calculate_keyword_score,
    compute_rule_based_score,
    evaluate_candidate_against_jd,
)

RULE_WEIGHT = 0.60
log = logging.getLogger(__name__)


def combine_ats_scores(
    rule_score: float, llm_score: Optional[float], rule_weight: float = RULE_WEIGHT
) -> float:
    """Blend available rule and model scores so either engine can be used independently."""
    rule = _clamp(_coerce_float(rule_score))
    if llm_score is None:
        return round(rule, 2)
    llm = _clamp(_coerce_float(llm_score))
    return round(rule * rule_weight + llm * (1 - rule_weight), 2)


def compute_final_ats(
    jd: Any,
    resume: Any,
    model: Optional[str] = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Calculate factor details and the final blended ATS score for one candidate."""
    factors = evaluate_candidate_against_jd(jd, resume)
    llm = get_ollama_evaluation(jd, resume, model) if use_llm else None
    llm_score = llm["score"] if llm else None
    scoring_mode = "hybrid" if llm_score is not None else "rule-only"
    log.info("ATS score calculated in %s mode", scoring_mode)
    return {
        "rule_based_score": factors.rule_based_score,
        "llm_based_score": llm_score,
        "llm_reason": llm["reason"] if llm else "",
        "final_ats_score": combine_ats_scores(factors.rule_based_score, llm_score),
        "scoring_mode": scoring_mode,
        "factors": factors.to_dict(),
    }


__all__ = [
    "ATSFactorResult",
    "RULE_WEIGHT",
    "calculate_keyword_score",
    "combine_ats_scores",
    "compute_final_ats",
    "compute_rule_based_score",
    "evaluate_candidate_against_jd",
    "extract_numeric_score",
    "get_batch_gemini_evaluations",
    "get_ollama_evaluation",
    "get_ollama_score",
    "reset_gemini_failure_state",
]
