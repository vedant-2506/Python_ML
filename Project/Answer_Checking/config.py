"""Configuration helpers for the Answer_Checking module."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_MAX_MARKS = 10.0
DIFFICULTY_MAX_MARKS = {
    "easy": 6.0,
    "medium": 12.0,
    "hard": 18.0,
}


def get_max_marks_for_difficulty(difficulty: str | None, fallback: float | None = None) -> float:
    """Return the configured question maximum, preserving legacy fallback for unknown difficulty."""

    if difficulty is not None:
        marks = DIFFICULTY_MAX_MARKS.get(str(difficulty).strip().lower())
        if marks is not None:
            return marks
    return DEFAULT_MAX_MARKS if fallback is None else float(fallback)


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "rankresume"
    user: str = "postgres"
    password: str = "postg"


def get_db_config() -> DatabaseConfig:
    """Read PostgreSQL configuration from environment variables.

    The project currently uses the shared RankResume settings; these are kept in
    a single place so the rest of the module can use the same connection
    convention as the existing modules.
    """

    return DatabaseConfig(
        host=os.getenv("RANKRESUME_DB_HOST", "localhost"),
        port=int(os.getenv("RANKRESUME_DB_PORT", "5432")),
        dbname=os.getenv("RANKRESUME_DB_NAME", "rankresume"),
        user=os.getenv("RANKRESUME_DB_USER", "postgres"),
        password=os.getenv("RANKRESUME_DB_PASSWORD", "postg"),
    )


def get_semantic_model_name() -> str:
    return os.getenv("ANSWER_CHECKING_SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def get_nli_model_name() -> str:
    return os.getenv("ANSWER_CHECKING_NLI_MODEL", "cross-encoder/nli-deberta-v3-small")


def get_default_calibration_thresholds() -> dict:
    return {
        "entailment_threshold": 0.6,
        "contradiction_threshold": 0.6,
        "neutral_threshold": 0.5,
    }
