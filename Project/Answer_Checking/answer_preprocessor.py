"""Lossless-enough preprocessing for technical candidate answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

TECHNICAL_PATTERNS = (
    r"\.net(?:\s+core)?", r"c\+\+", r"c#", r"node\.js", r"react\.js",
    r"spring[ -]boot", r"spring[ -]security", r"ci/cd", r"tcp/ip",
    r"rest\s+api", r"object[ -]oriented(?:\s+programming)?", r"key[ -]value",
)
TOKEN_PATTERN = re.compile(
    r"(?:" + "|".join(TECHNICAL_PATTERNS) + r"|[a-z0-9]+(?:[._+#/-][a-z0-9+#]+)*)",
    re.IGNORECASE,
)
STOP_WORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the to with"
    .split()
)


@dataclass(frozen=True)
class ProcessedText:
    text: str
    tokens: tuple[str, ...]


def normalize_text(value: object) -> str:
    """Normalize whitespace and case without stripping technical punctuation."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def preprocess(value: object, remove_stop_words: bool = True) -> ProcessedText:
    text = normalize_text(value)
    raw_tokens = tuple(match.group(0) for match in TOKEN_PATTERN.finditer(text))
    tokens = tuple(
        token for token in raw_tokens
        if not remove_stop_words or token not in STOP_WORDS
    )
    return ProcessedText(text=text, tokens=tokens)


def token_set(value: object) -> set[str]:
    return set(preprocess(value).tokens)