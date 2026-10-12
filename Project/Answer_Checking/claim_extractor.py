"""Utilities for extracting meaningful factual claims from candidate text."""

from __future__ import annotations

import re
from typing import List


def normalize_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_claims(text: str) -> List[str]:
    """Split candidate answers into a list of claim-like sentences.

    We intentionally keep the logic conservative: avoid over-splitting technical
    statements, negations, or conditional clauses that change meaning.
    """

    cleaned = normalize_text(text)
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?])\s+|\n+|;\s*", cleaned)
    claims: List[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence.split()) <= 2:
            claims.append(sentence)
            continue

        # Keep a sentence as one claim unless it contains a clear conjunction that
        # makes two independent factual statements. This avoids destroying the
        # meaning of technical conditions and negative statements.
        if re.search(r"\b(?:and|but|however|although|therefore|thus|so)\b", sentence, re.IGNORECASE):
            chunks = re.split(r"\s+(?:and|but|however|although|therefore|thus|so)\s+", sentence, flags=re.IGNORECASE)
            for chunk in chunks:
                chunk = chunk.strip(" ,;:-")
                if chunk:
                    claims.append(chunk)
        else:
            claims.append(sentence)

    return claims


def extract_claims(text: str) -> List[str]:
    return split_claims(text)
