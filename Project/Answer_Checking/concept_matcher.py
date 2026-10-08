"""Semantic-ish expected-concept coverage for technical answers."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from .answer_preprocessor import preprocess, token_set

ALIASES = {
    "base class": "parent class", "subclass": "child class", "derived class": "child class",
    "access control": "access modifiers", "access modifier": "access modifiers",
}


def parse_concepts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = re.split(r"[,;\n|]", value)
        except json.JSONDecodeError:
            value = re.split(r"[,;\n|]", value)
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def concept_coverage(expected_concepts: Any, candidate_answer: object) -> float:
    concepts = parse_concepts(expected_concepts)
    if not concepts or not preprocess(candidate_answer).tokens:
        return 0.0
    candidate_tokens = token_set(candidate_answer)
    candidate_text = preprocess(candidate_answer).text
    canonical_candidate_text = candidate_text
    for alias, canonical in ALIASES.items():
        canonical_candidate_text = canonical_candidate_text.replace(alias, canonical)
    matched = 0
    for concept in concepts:
        normalized = preprocess(concept).text
        canonical = ALIASES.get(normalized, normalized)
        concept_tokens = set(preprocess(canonical).tokens)
        direct = canonical in canonical_candidate_text or concept_tokens <= candidate_tokens
        fuzzy = SequenceMatcher(None, normalized, candidate_text).ratio() >= 0.42
        if direct or fuzzy:
            matched += 1
    return min(100.0, round(matched / len(concepts) * 100.0, 2))