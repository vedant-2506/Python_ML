# -*- coding: utf-8 -*-
"""
final_result.py
----------------
Utility for persisting the weighted final evaluation of a RankResume exam.

The workflow is:
1. All ten answers have been saved in ``answer_evaluation`` and evaluated.
2. This module aggregates the scores, computes the stage‑1 and stage‑2 averages
   and the final 60 % / 40 % weighted result.
3. The result is upserted into the ``final_evaluation_result`` table.

It deliberately **does not** touch any question‑generation logic – it merely
operates on already‑persisted rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict

from .database import (
    get_database_connection,
    get_exam_evaluation_rows,
)

FINAL_RESULT_TABLE_SQL_PATH = (
    Path(__file__).resolve().parent / "sql" / "create_final_evaluation_result.sql"
)


def _ensure_final_result_table(conn) -> None:
    """Create the final-result table if it does not yet exist."""
    with conn.cursor() as cur:
        cur.execute(FINAL_RESULT_TABLE_SQL_PATH.read_text(encoding="utf-8"))
    conn.commit()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _fetch_answer_score(conn, evaluation_id: int) -> float:
    """Return the ``answer_score`` for a given evaluation row.

    The ``answer_score`` column is stored as ``NUMERIC(5,2)``; we coerce it to
    ``float`` for arithmetic.  Missing scores are treated as ``0.0`` – this
    matches the existing evaluator which always writes a numeric value for
    completed rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT answer_score FROM public.answer_evaluation WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return 0.0
        return float(row[0])


def _separate_stage_rows(rows: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """Split the ten evaluation rows into stage‑1 and stage‑2 collections.

    Stage 1 rows are those whose ``question_source`` is ``"Question Bank"`` (or
    ``None`` for legacy data).  Stage 2 rows are those with ``"groq_llm"`` or
    ``"LLM"`` as the source.
    """
    stage1 = [r for r in rows if r.get("question_source") in ("Question Bank", None)]
    stage2 = [r for r in rows if r.get("question_source") in ("groq_llm", "LLM")]
    return stage1, stage2


def _calculate_averages(
    conn,
    stage_rows: List[Dict],
    divisor: int,
) -> float:
    """Calculate the average ``answer_score`` for the supplied rows.

    ``divisor`` is either ``6`` (stage 1) or ``4`` (stage 2).  The function
    returns the *un‑rounded* average; rounding is applied only when persisting
    the final result as required by the schema (``NUMERIC(5,2)``).
    """
    if not stage_rows:
        return 0.0
    total = sum(_fetch_answer_score(conn, r["evaluation_id"]) for r in stage_rows)
    return total / divisor


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_and_store_final_result(
    exam_id: str,
    candidate_id: int,
    jd_id: int,
) -> None:
    """Compute the weighted final result for a completed exam and upsert it.

    The function raises ``RuntimeError`` if any of the ten answers are missing
    or not in the ``Completed`` state – this guards against premature calls.

    Parameters
    ----------
    exam_id: str
        UUID of the exam session (from ``question_exam``).
    candidate_id: int
        Identifier of the candidate.
    jd_id: int
        Job‑description identifier.
    """
    # Load the ten rows for the exact scope.
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    if len(rows) < 10:
        raise RuntimeError(
            f"Expected 10 evaluation rows for exam_id={exam_id}, candidate_id={candidate_id}, jd_id={jd_id}, got {len(rows)}."
        )

    # Filter out superseded or review‑required rows – they should not be part of the final calc.
    completed_rows = [r for r in rows if r.get("evaluation_status") in {"Completed", "Review Required"}]
    if len(completed_rows) != 10:
        raise RuntimeError(
            f"All 10 answers must be in 'Completed' status before final calculation (found {len(completed_rows)})."
        )

    stage1_rows, stage2_rows = _separate_stage_rows(completed_rows)
    if len(stage1_rows) != 6 or len(stage2_rows) != 4:
        raise RuntimeError(
            f"Incorrect stage distribution: {len(stage1_rows)} stage‑1 rows, {len(stage2_rows)} stage‑2 rows."
        )

    # Perform the arithmetic inside a single DB connection for efficiency.
    conn = get_database_connection()
    try:
        _ensure_final_result_table(conn)
        first_six_avg = _calculate_averages(conn, stage1_rows, divisor=6)
        last_four_avg = _calculate_averages(conn, stage2_rows, divisor=4)
        final_result = 0.6 * first_six_avg + 0.4 * last_four_avg

        # Persist – use an UPSERT (ON CONFLICT) to avoid duplicate rows.
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.final_evaluation_result (
                    exam_id, jd_id, candidate_id,
                    first_six_average, last_four_average, final_result,
                    evaluation_status, calculated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'Completed', NOW())
                ON CONFLICT (exam_id, candidate_id) DO UPDATE
                SET first_six_average = EXCLUDED.first_six_average,
                    last_four_average = EXCLUDED.last_four_average,
                    final_result       = EXCLUDED.final_result,
                    evaluation_status  = EXCLUDED.evaluation_status,
                    calculated_at      = NOW();
                """,
                (
                    exam_id,
                    jd_id,
                    candidate_id,
                    round(first_six_avg, 2),
                    round(last_four_avg, 2),
                    round(final_result, 2),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def main(argv: List[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Calculate and store the final RankResume exam result."
    )
    parser.add_argument("exam_id", nargs="?", help="Exam UUID")
    parser.add_argument("candidate_id", nargs="?", type=int, help="Candidate identifier")
    parser.add_argument("jd_id", nargs="?", type=int, help="Job-description identifier")
    args = parser.parse_args(argv)

    exam_id = args.exam_id or input("Exam UUID: ").strip()
    if not exam_id:
        parser.error("exam_id must not be empty.")

    try:
        candidate_id = args.candidate_id
        if candidate_id is None:
            candidate_id = int(input("Candidate ID: ").strip())
        jd_id = args.jd_id
        if jd_id is None:
            jd_id = int(input("Job description ID: ").strip())
    except ValueError:
        parser.error("candidate_id and jd_id must be integers.")

    if candidate_id < 1 or jd_id < 1:
        parser.error("candidate_id and jd_id must be positive integers.")

    calculate_and_store_final_result(exam_id, candidate_id, jd_id)
    print("Final result persisted successfully.")


if __name__ == "__main__":
    main()
