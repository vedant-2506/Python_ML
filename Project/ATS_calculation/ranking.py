"""Candidate ranking from ATS scores stored in the project database."""

from typing import Any


def rank_candidates(connection: Any, jd_id: int | None = None) -> list[dict[str, Any]]:
    """Read scored candidates and assign competition ranks, preserving equal-score ties."""
    with connection.cursor() as cursor:
        if jd_id is not None:
            cursor.execute(
                "SELECT c.candidate_id, c.candidate_name, c.ats_score "
                "FROM candidate c "
                "JOIN ats_score a ON a.candidate_id = c.candidate_id "
                "WHERE a.jd_id = %s AND c.ats_score IS NOT NULL "
                "ORDER BY c.ats_score DESC, c.candidate_id ASC",
                (jd_id,),
            )
        else:
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
