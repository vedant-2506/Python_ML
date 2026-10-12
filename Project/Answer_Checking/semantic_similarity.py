"""Semantic similarity scoring for answer checking.

The default implementation uses a configurable sentence-transformer embedding
model. Model loading and inference errors are logged and raised rather than
silently replacing transformer similarity with a heuristic.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Callable, Dict, Tuple

import numpy as np

from .config import get_semantic_model_name


logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def load_semantic_model(model_name: str | None = None):
    """Load and cache the configured sentence-transformer model."""

    try:
        return _load_semantic_model(model_name or get_semantic_model_name())
    except Exception:
        logger.exception(
            "Failed to load semantic transformer model %r",
            model_name or get_semantic_model_name(),
        )
        raise


@lru_cache(maxsize=4)
def _load_semantic_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def provisional_calibration(similarity: float) -> float:
    """A simple provisional mapping from cosine similarity to a 0..1 score.

    This is intentionally conservative and should be replaced with calibrated
    grading data when that exists. Raw cosine similarity is not treated as a
    validated score without a mapping.
    """

    similarity = max(-1.0, min(1.0, float(similarity)))
    if similarity <= 0:
        return 0.0
    if similarity < 0.5:
        return similarity / 0.5
    return 0.5 + (similarity - 0.5) / 1.0


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    vec_a = np.asarray(vec_a, dtype=float)
    vec_b = np.asarray(vec_b, dtype=float)
    if vec_a.shape != vec_b.shape:
        raise ValueError(f"Embedding shape mismatch: {vec_a.shape} and {vec_b.shape} are not aligned")
    dot = float(np.dot(vec_a, vec_b))
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def calculate_semantic_score(
    expected_answer: str,
    candidate_answer: str,
    model: Any | None = None,
    calibration: Callable[[float], float] | None = None,
) -> Tuple[float, Dict[str, Any]]:
    """Return the semantic_score and metadata for the pair of answers."""

    expected = _normalize_text(expected_answer)
    candidate = _normalize_text(candidate_answer)
    if not expected or not candidate:
        return 0.0, {"status": "empty", "similarity": 0.0, "note": "Empty answer detected."}

    calibration_fn = calibration or provisional_calibration
    if model is None:
        model = load_semantic_model()

    if model is None:
        model = load_semantic_model()

    try:
        vector_a = np.asarray(model.encode(expected), dtype=float)
        vector_b = np.asarray(model.encode(candidate), dtype=float)
        if vector_a.shape != vector_b.shape:
            raise ValueError(f"Transformer embedding shape mismatch: {vector_a.shape} and {vector_b.shape} are not aligned")
        similarity = cosine_similarity(vector_a, vector_b)
        score = 100.0 * calibration_fn(similarity)
        return float(min(max(score, 0.0), 100.0)), {
            "status": "computed",
            "similarity": float(similarity),
            "note": "Transformer embedding similarity with provisional calibration.",
        }
    except Exception:
        logger.exception("Semantic embedding failed using %s", type(model).__name__)
        raise
