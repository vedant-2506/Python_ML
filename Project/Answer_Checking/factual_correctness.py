"""Factual correctness scoring based on claim extraction and NLI-style comparison."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np

from .claim_extractor import extract_claims
from .config import get_default_calibration_thresholds, get_nli_model_name


logger = logging.getLogger(__name__)


FACT_IMPORTANCE = {
    "essential": 3,
    "important": 2,
    "supporting": 1,
}


def normalize_expected_facts(expected_facts: Any) -> List[str]:
    """Convert existing metadata into a flat list of fact strings."""

    if expected_facts is None:
        return []
    if isinstance(expected_facts, str):
        return [expected_facts]
    if isinstance(expected_facts, list):
        facts: List[str] = []
        for item in expected_facts:
            if isinstance(item, dict):
                if "fact" in item:
                    facts.append(str(item["fact"]))
                elif "text" in item:
                    facts.append(str(item["text"]))
                else:
                    facts.extend(str(v) for v in item.values())
            else:
                facts.append(str(item))
        return facts
    if isinstance(expected_facts, dict):
        if "facts" in expected_facts:
            return normalize_expected_facts(expected_facts["facts"])
        if "expected_facts" in expected_facts:
            return normalize_expected_facts(expected_facts["expected_facts"])
        return [str(v) for v in expected_facts.values()]
    return [str(expected_facts)]


def get_fact_weight(detail: Any) -> int:
    """Extract a provisional fact weight from metadata if available."""

    if detail is None:
        return 1
    if isinstance(detail, dict):
        for key in ("importance", "weight", "priority"):
            if key in detail:
                value = str(detail[key]).lower()
                if value in FACT_IMPORTANCE:
                    return FACT_IMPORTANCE[value]
                try:
                    numeric = int(value)
                    return max(1, numeric)
                except ValueError:
                    pass
        if "fact" in detail and isinstance(detail["fact"], str):
            return 1
        return 1
    if isinstance(detail, str):
        value = detail.lower()
        if value in FACT_IMPORTANCE:
            return FACT_IMPORTANCE[value]
        return 1
    try:
        weight = int(detail)
    except (TypeError, ValueError):
        return 1
    return max(1, weight)


def load_nli_model(model_name: str | None = None):
    """Load and cache the configured cross-encoder NLI model."""

    try:
        return _load_nli_model(model_name or get_nli_model_name())
    except Exception:
        logger.exception("Failed to load NLI transformer model %r", model_name or get_nli_model_name())
        raise


@lru_cache(maxsize=4)
def _load_nli_model(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def _nli_label_indices(model: Any) -> Dict[str, int]:
    """Read the model's label mapping rather than assuming a class order."""

    model_config = getattr(getattr(model, "model", None), "config", None)
    id2label = getattr(model_config, "id2label", None)
    if not isinstance(id2label, dict):
        raise ValueError("NLI model config does not provide an id2label mapping.")

    indices = {
        str(label).strip().lower(): int(index)
        for index, label in id2label.items()
    }
    required_labels = {"entailment", "contradiction", "neutral"}
    if not required_labels.issubset(indices):
        raise ValueError(
            "NLI model label mapping must include entailment, contradiction, and neutral; "
            f"got {id2label!r}."
        )
    return {label: indices[label] for label in required_labels}


def run_nli_prediction(premise: str, hypothesis: str, model: Any | None = None) -> Dict[str, float]:
    """Run NLI-style comparison for one premise/hypothesis pair."""

    if model is None:
        model = load_nli_model()

    try:
        prediction = np.asarray(model.predict([(premise, hypothesis)]), dtype=float)
        if prediction.ndim == 2:
            if prediction.shape[0] != 1:
                raise ValueError(f"Expected one NLI prediction, got shape {prediction.shape}.")
            prediction = prediction[0]
        if prediction.ndim != 1 or prediction.size != 3:
            raise ValueError(f"Expected three NLI logits, got shape {prediction.shape}.")
        if not np.isfinite(prediction).all():
            raise ValueError("NLI model returned non-finite logits.")

        label_indices = _nli_label_indices(model)
        logits = prediction - np.max(prediction)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum()
        return {
            label: float(probabilities[index])
            for label, index in label_indices.items()
        }
    except Exception:
        logger.exception("NLI prediction failed using %s", type(model).__name__)
        raise


def classify_claim_status(probabilities: Dict[str, float], entailment_threshold: float = 0.6, contradiction_threshold: float = 0.6) -> str:
    if probabilities.get("entailment", 0.0) >= entailment_threshold and probabilities.get("entailment", 0.0) >= max(probabilities.get("contradiction", 0.0), probabilities.get("neutral", 0.0)):
        return "Supported"
    if probabilities.get("contradiction", 0.0) >= contradiction_threshold and probabilities.get("contradiction", 0.0) >= max(probabilities.get("entailment", 0.0), probabilities.get("neutral", 0.0)):
        return "Contradicted"
    return "Unverified"


def calculate_factual_correctness(
    candidate_answer: str,
    expected_facts: Any,
    model: Any | None = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute factual correctness based on extracted claims and verified facts."""

    thresholds = thresholds or get_default_calibration_thresholds()
    if candidate_answer is None or not str(candidate_answer).strip():
        return {
            "score": 0.0,
            "status": "Completed",
            "claims": [],
            "notes": "Empty candidate answer is handled before factual analysis.",
        }

    facts = normalize_expected_facts(expected_facts)
    if not facts:
        return {
            "score": None,
            "status": "Review Required",
            "claims": [],
            "notes": "No verified expected facts were available for this question.",
        }

    claims = extract_claims(candidate_answer)
    if not claims:
        return {
            "score": None,
            "status": "Review Required",
            "claims": [],
            "notes": "No meaningful factual claims could be extracted from the candidate answer.",
        }

    if model is None:
        model = load_nli_model()

    claim_scores = []
    claim_weights = []
    claim_details: List[Dict[str, Any]] = []
    entailment_threshold = thresholds.get("entailment_threshold", 0.6)
    contradiction_threshold = thresholds.get("contradiction_threshold", 0.6)

    for claim in claims:
        best_status = "Unverified"
        best_probabilities = {"entailment": 0.0, "contradiction": 0.0, "neutral": 1.0}
        best_weight = 1
        best_fact = None

        for fact in facts:
            probabilities = run_nli_prediction(fact, claim, model=model)
            status = classify_claim_status(probabilities, entailment_threshold, contradiction_threshold)
            weight = get_fact_weight({"importance": "supporting"})
            if isinstance(fact, dict):
                weight = get_fact_weight(fact)
            if status == "Supported" and probabilities.get("entailment", 0.0) >= best_probabilities.get("entailment", 0.0):
                best_status = "Supported"
                best_probabilities = probabilities
                best_weight = weight
                best_fact = fact
            elif status == "Contradicted" and probabilities.get("contradiction", 0.0) >= best_probabilities.get("contradiction", 0.0):
                best_status = "Contradicted"
                best_probabilities = probabilities
                best_weight = weight
                best_fact = fact
            elif best_status == "Unverified":
                best_status = "Unverified"
                best_probabilities = probabilities
                best_weight = weight
                best_fact = fact

        claim_score = None
        if best_status == "Supported":
            claim_score = 100.0
        elif best_status == "Contradicted":
            claim_score = 0.0
        else:
            entailment = best_probabilities.get("entailment", 0.0)
            contradiction = best_probabilities.get("contradiction", 0.0)
            claim_score = max(0.0, (entailment - contradiction) * 100.0)

        claim_scores.append(claim_score * best_weight)
        claim_weights.append(best_weight)

        claim_details.append(
            {
                "claim": claim,
                "fact": best_fact,
                "status": best_status,
                "probabilities": best_probabilities,
                "weight": best_weight,
                "score": claim_score,
            }
        )

    factual_score = sum(claim_scores) / sum(claim_weights)
    requires_review = any(detail["status"] == "Unverified" for detail in claim_details)
    return {
        "score": float(min(max(factual_score, 0.0), 100.0)),
        "status": "Review Required" if requires_review else "Completed",
        "claims": claim_details,
        "notes": (
            "Unverified claims received conservative entailment-margin scores; manual review is recommended."
            if requires_review
            else "Claim-level scores were combined using the configured claim weights."
        ),
    }
