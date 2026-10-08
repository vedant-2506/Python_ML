"""Question-type-independent answer scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .concept_matcher import concept_coverage
from .config import COMPLETENESS_WEIGHT, CONCEPT_WEIGHT, SEMANTIC_WEIGHT
from .embedding_engine import EmbeddingEngine
from .similarity_scorer import clamp_score, similarity_score


@dataclass(frozen=True)
class QuestionContext:
    question: str
    reference_answer: str
    expected_concepts: Any
    difficulty: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    semantic_score: float
    concept_score: float
    completeness_score: float
    final_score: float
    candidate_vector: list[float]
    reference_vector: list[float]


class AnswerEvaluator:
    def __init__(self, embedding_engine: EmbeddingEngine | None = None):
        self.embedding_engine = embedding_engine or EmbeddingEngine()

    def evaluate(self, context: QuestionContext, candidate_answer: object) -> EvaluationResult:
        if not str(context.reference_answer or "").strip():
            raise ValueError("reference answer is required and cannot be empty")
        candidate_vector = self.embedding_engine.vectorize(candidate_answer)
        reference_vector = self.embedding_engine.vectorize(context.reference_answer)
        semantic = similarity_score(candidate_vector, reference_vector)
        concepts = concept_coverage(context.expected_concepts, candidate_answer)
        completeness = self._completeness(candidate_answer, semantic, concepts)
        final = clamp_score(
            SEMANTIC_WEIGHT * semantic + CONCEPT_WEIGHT * concepts + COMPLETENESS_WEIGHT * completeness
        )
        return EvaluationResult(semantic, concepts, completeness, final, candidate_vector, reference_vector)

    @staticmethod
    def _completeness(candidate_answer: object, semantic: float, concepts: float) -> float:
        token_count = len(str(candidate_answer or "").split())
        if token_count == 0:
            return 0.0
        length_quality = min(1.0, token_count / 12.0) * 100.0
        return clamp_score(0.6 * semantic + 0.3 * concepts + 0.1 * length_quality)

    @staticmethod
    def average(scores: Iterable[float]) -> float:
        values = [clamp_score(score) for score in scores]
        if not values:
            raise ValueError("at least one score is required")
        return clamp_score(sum(values) / len(values))

    def evaluate_many(self, contexts: Iterable[QuestionContext], answers: Iterable[object]) -> list[EvaluationResult]:
        return [self.evaluate(context, answer) for context, answer in zip(contexts, answers)]