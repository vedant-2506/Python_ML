"""Bounded cosine similarity and score conversion."""

from __future__ import annotations

import math


def cosine_similarity(first: list[float], second: list[float]) -> float:
    if not first or not second or len(first) != len(second):
        return 0.0
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if not first_norm or not second_norm:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second)) / (first_norm * second_norm)))


def similarity_score(first: list[float], second: list[float]) -> float:
    return clamp_score(max(0.0, cosine_similarity(first, second)) * 100.0)


def clamp_score(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return round(max(0.0, min(100.0, value)), 2)