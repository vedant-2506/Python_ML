"""Deterministic scoring and adaptive difficulty policy for Stage 2."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

STAGE1_MAX_MARKS = Decimal("60")
EXPECTED_STAGE1_DIFFICULTIES = ("Easy", "Easy", "Easy", "Medium", "Medium", "Hard")
DIFFICULTY_MARKS = {"Easy": Decimal("6"), "Medium": Decimal("12"), "Hard": Decimal("18")}


def calculate_percentage(evaluations: Iterable[dict[str, Any]]) -> Decimal:
    """Validate six completed evaluations and calculate the percentage out of 60."""
    rows = list(evaluations)
    if len(rows) != 6:
        raise ValueError(f"exactly six Stage 1 evaluations are required; found {len(rows)}")

    ordered = sorted(rows, key=lambda row: int(row.get("question_order", 0)))
    if sorted(row.get("difficulty") for row in ordered) != sorted(EXPECTED_STAGE1_DIFFICULTIES):
        raise ValueError("Stage 1 difficulty distribution is not 3 Easy, 2 Medium, 1 Hard")

    total_max = Decimal("0")
    obtained = Decimal("0")
    for row in ordered:
        if row.get("evaluation_status") != "Completed":
            raise ValueError(
                f"Stage 1 evaluation {row.get('evaluation_id', '')} is "
                f"{row.get('evaluation_status')!r}; only Completed results are eligible"
            )
        try:
            marks = Decimal(str(row["obtained_marks"]))
            max_marks = Decimal(str(row.get("max_marks") or DIFFICULTY_MARKS[row["difficulty"]]))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Stage 1 evaluations contain missing or invalid marks") from exc
        if not marks.is_finite() or not max_marks.is_finite() or marks < 0 or max_marks <= 0 or marks > max_marks:
            raise ValueError("Stage 1 marks must be finite and within each question maximum")
        expected_max = DIFFICULTY_MARKS[row["difficulty"]]
        if max_marks != expected_max:
            raise ValueError(f"{row['difficulty']} question maximum must be {expected_max}")
        obtained += marks
        total_max += max_marks

    if total_max != STAGE1_MAX_MARKS:
        raise ValueError(f"Stage 1 maximum must total 60; found {total_max}")
    percentage = (obtained / STAGE1_MAX_MARKS * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if not Decimal("0") <= percentage <= Decimal("100"):
        raise ValueError("calculated percentage is outside 0-100")
    return percentage


DEFAULT_STAGE2_DISTRIBUTION: dict[str, int] = {"Easy": 2, "Medium": 2, "Hard": 0}


def determine_stage2_difficulty(percentage: Any) -> dict[str, int]:
    """Return the exact four-question distribution after whole-percent rounding."""
    try:
        score = Decimal(str(percentage))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("percentage must be numeric") from exc
    if not score.is_finite() or score < 0 or score > 100:
        raise ValueError("percentage must be between 0 and 100")
    rounded = int(score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if rounded <= 59:
        return {"Easy": 3, "Medium": 1, "Hard": 0}
    if rounded <= 80:
        return {"Easy": 2, "Medium": 2, "Hard": 0}
    return {"Easy": 0, "Medium": 3, "Hard": 1}


def resolve_stage2_difficulty(
    evaluations: Iterable[dict[str, Any]] | None = None,
) -> tuple[dict[str, int], Decimal | None, bool]:
    """Resolve Stage 2 difficulty distribution.

    If six completed evaluations exist with valid marks, calculates genuine
    percentage and returns (adaptive_distribution, percentage, True).

    If evaluations are not yet completed (or missing), returns the documented
    default distribution without faking score or marks:
    (DEFAULT_STAGE2_DISTRIBUTION, None, False).
    """
    if evaluations is None:
        return dict(DEFAULT_STAGE2_DISTRIBUTION), None, False
    try:
        percentage = calculate_percentage(evaluations)
        return determine_stage2_difficulty(percentage), percentage, True
    except (ValueError, TypeError):
        return dict(DEFAULT_STAGE2_DISTRIBUTION), None, False
