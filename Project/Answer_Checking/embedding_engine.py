"""Reusable sentence vectors with an optional local Word2Vec backend."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .answer_preprocessor import preprocess
from .config import EMBEDDING_DIMENSION


class EmbeddingEngine:
    """Create pooled vectors once per text and reuse them for repeated evaluations."""

    def __init__(self, model: Any = None, dimension: int = EMBEDDING_DIMENSION):
        self.model = model
        self.dimension = int(getattr(model, "vector_size", dimension))
        self._cache: dict[str, list[float]] = {}

    @classmethod
    def from_word2vec(cls, model_path: str, dimension: int = EMBEDDING_DIMENSION):
        if not model_path:
            return cls(dimension=dimension)
        try:
            from gensim.models import Word2Vec
            return cls(Word2Vec.load(str(Path(model_path))).wv)
        except (ImportError, OSError, ValueError) as exc:
            raise RuntimeError(f"Unable to load Word2Vec model at {model_path}: {exc}") from exc

    @property
    def status(self) -> str:
        return "word2vec" if self.model is not None else "local-hashed-fallback"

    def vectorize(self, value: object) -> list[float]:
        text = preprocess(value, remove_stop_words=False).text
        if text in self._cache:
            return list(self._cache[text])
        tokens = preprocess(value, remove_stop_words=False).tokens
        if not tokens:
            vector = [0.0] * self.dimension
        elif self.model is not None:
            vectors = [self.model[token] for token in tokens if token in self.model]
            vector = self._mean(vectors) if vectors else [0.0] * self.dimension
        else:
            vector = self._hashed_vector(tokens)
        self._cache[text] = vector
        return list(vector)

    def _hashed_vector(self, tokens: tuple[str, ...]) -> list[float]:
        vector = [0.0] * self.dimension
        features = list(tokens) + [f"{left} {right}" for left, right in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        return self._unit(vector)

    @staticmethod
    def _mean(vectors: list[Any]) -> list[float]:
        dimension = len(vectors[0])
        return EmbeddingEngine._unit([sum(float(vector[i]) for vector in vectors) / len(vectors) for i in range(dimension)])

    @staticmethod
    def _unit(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector