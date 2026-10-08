"""Configuration for answer evaluation."""

import os

SEMANTIC_WEIGHT = float(os.getenv("ANSWER_SEMANTIC_WEIGHT", "0.50"))
CONCEPT_WEIGHT = float(os.getenv("ANSWER_CONCEPT_WEIGHT", "0.30"))
COMPLETENESS_WEIGHT = float(os.getenv("ANSWER_COMPLETENESS_WEIGHT", "0.20"))
EMBEDDING_DIMENSION = int(os.getenv("ANSWER_EMBEDDING_DIMENSION", "256"))
WORD2VEC_MODEL_PATH = os.getenv("ANSWER_WORD2VEC_MODEL", "")

if abs(SEMANTIC_WEIGHT + CONCEPT_WEIGHT + COMPLETENESS_WEIGHT - 1.0) > 1e-9:
    raise ValueError("Answer evaluation weights must sum to 1.0")