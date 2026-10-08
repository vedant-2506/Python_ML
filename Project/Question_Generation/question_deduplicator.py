"""Lightweight exact and near-duplicate detection without an embedding service."""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_WORDS = re.compile(r"[a-z0-9+#.]+")


def normalize(text: str) -> str:
    return " ".join(_WORDS.findall(text.lower()))


def shingles(text: str) -> set[str]:
    words = normalize(text).split()
    return {" ".join(words[index:index + 3]) for index in range(max(0, len(words) - 2))}


def similarity(left: str, right: str) -> float:
    a, b = shingles(left), shingles(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def duplicate_counts(values: Iterable[str], near_threshold: float = 0.86) -> tuple[int, int]:
    seen: set[str] = set()
    buckets: dict[str, list[set[str]]] = {}
    exact = 0
    near = 0
    for value in values:
        key = normalize(value)
        if key in seen:
            exact += 1
            continue
        bucket = " ".join(key.split()[:3])
        current_shingles = shingles(value)
        if any(
            len(current_shingles & previous) / len(current_shingles | previous) >= near_threshold
            for previous in buckets.get(bucket, [])
            if current_shingles and previous
        ):
            near += 1
        seen.add(key)
        buckets.setdefault(bucket, []).append(current_shingles)
    return exact, near


def answer_fingerprint(answer: str) -> Counter[str]:
    return Counter(normalize(answer).split())
