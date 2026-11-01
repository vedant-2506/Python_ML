"""Reference-grounded factual correctness using extracted claims and NLI.

An NLI 'neutral' prediction means not verified by the supplied reference;
it does not imply a false candidate statement.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np

from .claim_extractor import extract_claims
from .config import get_default_calibration_thresholds, get_nli_model_name

logger = logging.getLogger(__name__)
FACT_IMPORTANCE = {"essential": 3, "important": 2, "supporting": 1}


def _fact_records(expected_facts: Any) -> List[Dict[str, Any]]:
    """Preserve text and importance while accepting existing metadata shapes."""
    if expected_facts is None:
        return []
    if isinstance(expected_facts, dict):
        for key in ("facts", "expected_facts"):
            if key in expected_facts:
                return _fact_records(expected_facts[key])
        if "fact" in expected_facts or "text" in expected_facts:
            text = str(expected_facts.get("fact", expected_facts.get("text", ""))).strip()
            return [{"fact": text, "weight": get_fact_weight(expected_facts)}] if text else []
        return _fact_records(list(expected_facts.values()))
    if isinstance(expected_facts, (list, tuple)):
        records = []
        for item in expected_facts:
            records.extend(_fact_records(item))
        return records
    text = str(expected_facts).strip()
    return [{"fact": text, "weight": 1}] if text else []


def normalize_expected_facts(expected_facts: Any) -> List[str]:
    """Convert supported metadata shapes into a list of fact strings."""
    return [record["fact"] for record in _fact_records(expected_facts)]


def get_fact_weight(detail: Any) -> int:
    if detail is None:
        return 1
    if isinstance(detail, dict):
        for key in ("importance", "weight", "priority"):
            if key in detail:
                return get_fact_weight(detail[key])
        return 1
    if isinstance(detail, str) and detail.strip().lower() in FACT_IMPORTANCE:
        return FACT_IMPORTANCE[detail.strip().lower()]
    try:
        return max(1, int(detail))
    except (TypeError, ValueError):
        return 1


def load_nli_model(model_name: str | None = None):
    name = model_name or get_nli_model_name()
    try:
        return _load_nli_model(name)
    except Exception:
        logger.exception("Failed to load NLI model %r", name)
        raise


@lru_cache(maxsize=4)
def _load_nli_model(model_name: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model_name)


def _nli_label_indices(model: Any) -> Dict[str, int]:
    config = getattr(getattr(model, "model", None), "config", None)
    mapping = getattr(config, "id2label", None)
    if not isinstance(mapping, dict):
        raise ValueError("NLI model must provide config.id2label.")
    indices = {str(label).strip().lower(): int(index) for index, label in mapping.items()}
    required = {"entailment", "contradiction", "neutral"}
    if not required.issubset(indices):
        raise ValueError(f"NLI label mapping missing required labels: {mapping!r}")
    return {label: indices[label] for label in required}


def run_nli_prediction(premise: str, hypothesis: str, model: Any | None = None) -> Dict[str, float]:
    """Return three class probabilities, supporting logits or probability outputs."""
    if model is None:
        model = load_nli_model()
    try:
        raw = np.asarray(model.predict([(premise, hypothesis)]), dtype=float)
        if raw.ndim == 2 and raw.shape[0] == 1:
            raw = raw[0]
        if raw.ndim != 1 or raw.size != 3 or not np.isfinite(raw).all():
            raise ValueError(f"Expected one finite three-class NLI prediction, got {raw!r}")
        indices = _nli_label_indices(model)
        # Many CrossEncoder models output raw logits, but some already output probabilities.
        if np.all(raw >= 0) and np.all(raw <= 1) and np.isclose(raw.sum(), 1.0, atol=1e-4):
            probs = raw / raw.sum()
        else:
            shifted = raw - np.max(raw)
            exp = np.exp(shifted)
            probs = exp / exp.sum()
        return {label: float(probs[index]) for label, index in indices.items()}
    except Exception:
        logger.exception("NLI prediction failed using %s", type(model).__name__)
        raise


def classify_claim_status(
    probabilities: Dict[str, float],
    entailment_threshold: float = 0.6,
    contradiction_threshold: float = 0.6,
) -> str:
    ent = probabilities.get("entailment", 0.0)
    con = probabilities.get("contradiction", 0.0)
    neu = probabilities.get("neutral", 0.0)
    if ent >= entailment_threshold and ent >= max(con, neu):
        return "Supported"
    if con >= contradiction_threshold and con >= max(ent, neu):
        return "Contradicted"
    return "Unverified"


def calculate_factual_correctness(
    candidate_answer: str,
    expected_facts: Any,
    model: Any | None = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Return a numeric 0..100 score in user-defined bands.

    This is *reference-grounded*, not an independent truth checker. The bands
    are grading policy, not calibrated probabilities of factual correctness.
    An ambiguous reference is flagged for review.
    """
    if not candidate_answer or not str(candidate_answer).strip():
        return {"score": 0.0, "status": "Completed", "classification": "Incorrect",
                "claims": [], "notes": "Empty answer."}

    facts = _fact_records(expected_facts)
    claims = [str(c).strip() for c in extract_claims(str(candidate_answer)) if str(c).strip()]
    if not facts or not claims:
        # Numeric fallback for database compatibility; not a finding of falsity.
        return {"score": 0.0, "status": "Review Required", "classification": "Unassessable",
                "claims": [], "notes": "Missing reference facts or extractable claims; 0 is a placeholder, not a factual judgment."}

    thresholds = thresholds if thresholds is not None else get_default_calibration_thresholds()
    ent_threshold = float(thresholds.get("entailment_threshold", 0.6))
    con_threshold = float(thresholds.get("contradiction_threshold", 0.6))
    if model is None:
        model = load_nli_model()

    # For factual correctness, compare candidate claims with expected facts.
    # Also check coverage in the reverse direction: an answer may paraphrase
    # an expected fact without each short extracted claim being entailed.
    details: List[Dict[str, Any]] = []
    supported_count = contradicted_count = 0
    for claim in claims:
        comparisons = []
        for record in facts:
            probs = run_nli_prediction(record["fact"], claim, model=model)
            label = classify_claim_status(probs, ent_threshold, con_threshold)
            comparisons.append({"fact": record["fact"], "weight": record["weight"],
                                "status": label, "probabilities": probs})
        supported = [x for x in comparisons if x["status"] == "Supported"]
        contradicted = [x for x in comparisons if x["status"] == "Contradicted"]
        if supported and contradicted:
            label = "Unverified"  # contradictory reference evidence
            best = max(comparisons, key=lambda x: max(x["probabilities"].values()))
        elif supported:
            label = "Supported"
            best = max(supported, key=lambda x: x["probabilities"]["entailment"])
            supported_count += 1
        elif contradicted:
            label = "Contradicted"
            best = max(contradicted, key=lambda x: x["probabilities"]["contradiction"])
            contradicted_count += 1
        else:
            label = "Unverified"
            best = max(comparisons, key=lambda x: x["probabilities"]["entailment"])
        details.append({"claim": claim, "fact": best["fact"], "status": label,
                        "probabilities": best["probabilities"], "weight": best["weight"],
                        "score": 100.0 if label == "Supported" else 0.0 if label == "Contradicted" else None})

    # Coverage measures how much of the reference the entire candidate answer
    # establishes. It is used here only to determine the grading band.
    # If coverage is already a separate factor in the overall grade, remove
    # this contribution to avoid double counting.
    covered_weight = total_weight = 0
    for record in facts:
        total_weight += record["weight"]
        # Sentence/claim chunks avoid NLI truncation on long candidate answers.
        best_ent = 0.0
        for claim in claims:
            probs = run_nli_prediction(claim, record["fact"], model=model)
            if classify_claim_status(probs, ent_threshold, con_threshold) == "Supported":
                best_ent = max(best_ent, probs["entailment"])
        if best_ent:
            covered_weight += record["weight"]
    coverage = covered_weight / total_weight
    support_rate = supported_count / len(claims)
    contradiction_rate = contradicted_count / len(claims)
    unverified_count = len(claims) - supported_count - contradicted_count

    # Policy bands: Incorrect 0-10, Partially Correct 60-80, Correct 80-100.
    # Avoid labeling unsupported-but-not-contradicted material as incorrect.
    if contradiction_rate >= 0.5 and supported_count == 0 and coverage < 0.25:
        classification = "Incorrect"
        score = round(10.0 * (1.0 - contradiction_rate), 2)
    elif contradiction_rate == 0 and coverage >= 0.8 and support_rate >= 0.6:
        classification = "Correct"
        score = round(80.0 + 20.0 * (0.6 * coverage + 0.4 * support_rate), 2)
    else:
        classification = "Partially Correct"
        # Provisional middle band; review if reference is inadequate.
        evidence = 0.55 * coverage + 0.45 * support_rate
        score = round(60.0 + 20.0 * max(0.0, min(1.0, evidence)), 2)

    needs_review = unverified_count > 0 or (coverage == 0 and supported_count == 0 and contradicted_count == 0)
    return {
        "score": float(min(100.0, max(0.0, score))),
        "status": "Review Required" if needs_review else "Completed",
        "classification": classification,
        "claims": details,
        "coverage": round(coverage, 4),
        "supported_claims": supported_count,
        "contradicted_claims": contradicted_count,
        "unverified_claims": unverified_count,
        "notes": ("Provisional band score; unverified claims need review. "
                  "Neutral NLI evidence is not proof of incorrectness."
                  if needs_review else "Reference-grounded NLI band score."),
    }
