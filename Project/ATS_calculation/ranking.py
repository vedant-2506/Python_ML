"""Candidate ranking from ATS scores stored in the project database."""

from typing import Any


def rank_candidates(connection: Any) -> list[dict[str, Any]]:
    """Read scored candidates and assign competition ranks, preserving equal-score ties."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT candidate_id, candidate_name, ats_score FROM candidate "
            "WHERE ats_score IS NOT NULL ORDER BY ats_score DESC, candidate_id ASC"
        )
        rows = cursor.fetchall()

    ranked: list[dict[str, Any]] = []
    previous_score: float | None = None
    current_rank = 0
    for index, (candidate_id, name, ats_score) in enumerate(rows, 1):
        score = float(ats_score)
        if previous_score is None or score != previous_score:
            current_rank = index
        previous_score = score
        ranked.append({
            "rank": current_rank,
            "candidate_id": candidate_id,
            "candidate_name": name,
            "ats_score": round(score, 2),
        })
    return ranked
