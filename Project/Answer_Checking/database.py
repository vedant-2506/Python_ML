"""Database helpers for answer submission and evaluation tracking."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psycopg2

from .config import get_db_config, get_max_marks_for_difficulty


SQL_DIR = Path(__file__).resolve().parent / "sql"
TABLE_SQL_PATH = SQL_DIR / "create_answer_evaluation.sql"


def get_database_connection():
    """Create a PostgreSQL connection using the project environment settings."""

    config = get_db_config()
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
    )


def ensure_answer_evaluation_table(connection=None):
    """Create the answer_evaluation table if it does not yet exist."""

    own_connection = connection is None
    conn = connection or get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(TABLE_SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        if own_connection and conn is not None:
            conn.close()


def get_question_details(
    jd_id: int,
    question_id: int,
    exam_id: str | None = None,
    question_source: str | None = None,
    stage: int | None = None,
) -> Dict[str, Any]:
    """Fetch a Stage 1 or generated question snapshot for evaluation.

    The live project schema stores the expected answer as `reference_answer`, so
    we map that value to the evaluation's `expected_answer` field.
    Differentiates between Stage 1 (Question Bank) and Stage 2 (LLM) questions.
    """

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            # If explicitly Stage 2 / groq_llm
            if question_source in ("groq_llm", "LLM") or stage == 2:
                query_ai = """
                    SELECT jd_id, ai_question_exam_id, question, COALESCE(reference_answer, answer),
                           expected_concepts, difficulty, skill, ai_question_exam_id
                    FROM public.ai_question_exam
                    WHERE jd_id = %s AND ai_question_exam_id = %s
                """
                params_ai: list[Any] = [jd_id, question_id]
                if exam_id is not None:
                    query_ai += " AND exam_id = %s"
                    params_ai.append(str(exam_id))
                cursor.execute(query_ai, params_ai)
                ai_row = cursor.fetchone()
                if ai_row is not None:
                    return {
                        "jd_id": ai_row[0],
                        "question_id": ai_row[1],
                        "question": ai_row[2],
                        "expected_answer": ai_row[3],
                        "expected_concepts": ai_row[4],
                        "difficulty": ai_row[5],
                        "skill": ai_row[6],
                        "exam_question_id": ai_row[7],
                        "question_source": "groq_llm",
                    }
                # Fallback to question_exam stage 2
                query_q2 = """
                    SELECT jd_id, generated_question_id, question, reference_answer,
                           expected_concepts, difficulty, skill, exam_question_id
                    FROM public.question_exam
                    WHERE jd_id = %s AND (generated_question_id = %s OR exam_question_id = %s) AND stage = 2
                """
                params_q2: list[Any] = [jd_id, question_id, question_id]
                if exam_id is not None:
                    query_q2 += " AND exam_id = %s"
                    params_q2.append(str(exam_id))
                query_q2 += " ORDER BY exam_question_id DESC LIMIT 1"
                cursor.execute(query_q2, params_q2)
                row_q2 = cursor.fetchone()
                if row_q2 is not None:
                    return {
                        "jd_id": row_q2[0],
                        "question_id": row_q2[1],
                        "question": row_q2[2],
                        "expected_answer": row_q2[3],
                        "expected_concepts": row_q2[4],
                        "difficulty": row_q2[5],
                        "skill": row_q2[6],
                        "exam_question_id": row_q2[7],
                        "question_source": "groq_llm",
                    }
                raise ValueError(f"No Stage 2 question found for jd_id={jd_id} and question_id={question_id}.")

            # If explicitly Stage 1 / Question Bank or unspecified
            if question_source in ("Question Bank", "bankresume") or stage == 1:
                query_q1 = """
                    SELECT jd_id, question_id, question, reference_answer,
                           expected_concepts, difficulty, skill, exam_question_id
                    FROM public.question_exam
                    WHERE jd_id = %s AND question_id = %s AND stage = 1
                """
                params_q1: list[Any] = [jd_id, question_id]
                if exam_id is not None:
                    query_q1 += " AND exam_id = %s"
                    params_q1.append(str(exam_id))
                query_q1 += " ORDER BY exam_question_id DESC LIMIT 1"
                cursor.execute(query_q1, params_q1)
                row_q1 = cursor.fetchone()
                if row_q1 is not None:
                    return {
                        "jd_id": row_q1[0],
                        "question_id": row_q1[1],
                        "question": row_q1[2],
                        "expected_answer": row_q1[3],
                        "expected_concepts": row_q1[4],
                        "difficulty": row_q1[5],
                        "skill": row_q1[6],
                        "exam_question_id": row_q1[7],
                        "question_source": "Question Bank",
                    }
                raise ValueError(f"No Stage 1 question found for jd_id={jd_id} and question_id={question_id}.")

            # Unspecified: Check question_exam stage 1 first
            query_q1 = """
                SELECT jd_id, question_id, question, reference_answer,
                       expected_concepts, difficulty, skill, exam_question_id
                FROM public.question_exam
                WHERE jd_id = %s AND question_id = %s AND stage = 1
            """
            params_q1 = [jd_id, question_id]
            if exam_id is not None:
                query_q1 += " AND exam_id = %s"
                params_q1.append(str(exam_id))
            query_q1 += " ORDER BY exam_question_id DESC LIMIT 1"
            cursor.execute(query_q1, params_q1)
            row_q1 = cursor.fetchone()
            if row_q1 is not None:
                return {
                    "jd_id": row_q1[0],
                    "question_id": row_q1[1],
                    "question": row_q1[2],
                    "expected_answer": row_q1[3],
                    "expected_concepts": row_q1[4],
                    "difficulty": row_q1[5],
                    "skill": row_q1[6],
                    "exam_question_id": row_q1[7],
                    "question_source": "Question Bank",
                }

            # Then check ai_question_exam
            query_ai = """
                SELECT jd_id, ai_question_exam_id, question, COALESCE(reference_answer, answer),
                       expected_concepts, difficulty, skill, ai_question_exam_id
                FROM public.ai_question_exam
                WHERE jd_id = %s AND ai_question_exam_id = %s
            """
            params_ai = [jd_id, question_id]
            if exam_id is not None:
                query_ai += " AND exam_id = %s"
                params_ai.append(str(exam_id))
            cursor.execute(query_ai, params_ai)
            ai_row = cursor.fetchone()
            if ai_row is not None:
                return {
                    "jd_id": ai_row[0],
                    "question_id": ai_row[1],
                    "question": ai_row[2],
                    "expected_answer": ai_row[3],
                    "expected_concepts": ai_row[4],
                    "difficulty": ai_row[5],
                    "skill": ai_row[6],
                    "exam_question_id": ai_row[7],
                    "question_source": "groq_llm",
                }

            # Then check question_exam stage 2
            query_q2 = """
                SELECT jd_id, generated_question_id, question, reference_answer,
                       expected_concepts, difficulty, skill, exam_question_id
                FROM public.question_exam
                WHERE jd_id = %s AND (generated_question_id = %s OR exam_question_id = %s) AND stage = 2
            """
            params_q2 = [jd_id, question_id, question_id]
            if exam_id is not None:
                query_q2 += " AND exam_id = %s"
                params_q2.append(str(exam_id))
            query_q2 += " ORDER BY exam_question_id DESC LIMIT 1"
            cursor.execute(query_q2, params_q2)
            row_q2 = cursor.fetchone()
            if row_q2 is not None:
                return {
                    "jd_id": row_q2[0],
                    "question_id": row_q2[1],
                    "question": row_q2[2],
                    "expected_answer": row_q2[3],
                    "expected_concepts": row_q2[4],
                    "difficulty": row_q2[5],
                    "skill": row_q2[6],
                    "exam_question_id": row_q2[7],
                    "question_source": "groq_llm",
                }

        raise ValueError(f"No question found for jd_id={jd_id} and question_id={question_id}.")
    finally:
        conn.close()


def get_stage1_questions(jd_id: int, exam_id: str | None = None) -> List[Dict[str, Any]]:
    """Return the latest Stage 1 question set for a JD in question order."""

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            if exam_id is None:
                query = """
                SELECT question_id, question, exam_question_id, difficulty
                FROM public.question_exam
                WHERE jd_id = %s
                  AND stage = 1
                  AND exam_id = (
                      SELECT exam_id
                      FROM public.question_exam
                      WHERE jd_id = %s AND stage = 1
                      GROUP BY exam_id
                      ORDER BY MAX(created_at) DESC, exam_id DESC
                      LIMIT 1
                  )
                ORDER BY question_order
                """
                parameters = (jd_id, jd_id)
            else:
                query = """
                SELECT question_id, question, exam_question_id, difficulty
                FROM public.question_exam
                WHERE jd_id = %s
                  AND stage = 1
                  AND exam_id = %s
                ORDER BY question_order
                """
                parameters = (jd_id, exam_id)
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

        questions = [
            {
                "question_id": row[0],
                "question": row[1],
                "exam_question_id": row[2],
                "difficulty": row[3] if len(row) > 3 else "Medium",
            }
            for row in rows
        ]
        if len(questions) != 6:
            raise ValueError(
                f"JD {jd_id} must have exactly 6 Stage 1 questions; found {len(questions)}."
            )
        return questions
    finally:
        conn.close()


def get_latest_exam_id(jd_id: int) -> str:
    """Return the latest Stage 1 exam session containing six questions."""

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT exam_id
                FROM public.question_exam
                WHERE jd_id = %s AND stage = 1
                GROUP BY exam_id
                HAVING COUNT(*) = 6
                ORDER BY MAX(created_at) DESC, exam_id DESC
                LIMIT 1
                """,
                (jd_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError(f"No complete Stage 1 exam session found for JD {jd_id}.")
        return str(row[0])
    finally:
        conn.close()


def get_candidate_exam_ids(jd_id: int, candidate_id: int) -> List[str]:
    """Return Stage 1 sessions with recorded answers for one candidate and JD."""

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT ae.exam_id
                FROM public.answer_evaluation ae
                WHERE ae.jd_id = %s AND ae.candidate_id = %s
                  AND ae.exam_id IS NOT NULL
                  AND ae.evaluation_status <> 'Superseded'
                GROUP BY ae.exam_id
                ORDER BY MAX(ae.evaluation_id) DESC
                """,
                (jd_id, candidate_id),
            )
            return [str(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_candidate_all_exam_ids(jd_id: int, candidate_id: int) -> List[str]:
    """Return all distinct exam IDs where the candidate has recorded answers for a JD."""
    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ae.exam_id
                FROM public.answer_evaluation ae
                WHERE ae.jd_id = %s AND ae.candidate_id = %s
                  AND ae.exam_id IS NOT NULL
                  AND ae.evaluation_status <> 'Superseded'
                ORDER BY ae.exam_id
                """,
                (jd_id, candidate_id),
            )
            return [str(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_exam_evaluation_rows(exam_id: str, candidate_id: int, jd_id: int) -> List[Dict[str, Any]]:
    """Return all saved answer/evaluation rows for one exact exam scope."""

    conn = get_database_connection()
    try:
        ensure_answer_evaluation_table(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT evaluation_id, question_id, evaluation_status,
                       obtained_marks, max_marks, candidate_answer, question_source
                FROM public.answer_evaluation
                WHERE exam_id = %s AND candidate_id = %s AND jd_id = %s
                ORDER BY evaluation_id
                """,
                (exam_id, candidate_id, jd_id),
            )
            return [
                {
                    "evaluation_id": row[0],
                    "question_id": row[1],
                    "evaluation_status": row[2],
                    "obtained_marks": row[3],
                    "max_marks": row[4],
                    "candidate_answer": row[5],
                    "question_source": row[6],
                }
                for row in cursor.fetchall()
            ]
    finally:
        conn.close()


def supersede_duplicate_pending_stage1(
    exam_id: str, candidate_id: int, jd_id: int
) -> int:
    """Preserve, but deactivate, pending duplicates when one completed row exists."""

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT ae.evaluation_id, ae.question_id, ae.evaluation_status
                FROM public.answer_evaluation ae
                JOIN public.question_exam qe
                  ON qe.exam_id = ae.exam_id
                 AND qe.jd_id = ae.jd_id
                 AND qe.question_id = ae.question_id
                 AND qe.stage = 1
                WHERE ae.exam_id = %s AND ae.candidate_id = %s AND ae.jd_id = %s
                ORDER BY ae.question_id, ae.evaluation_id
                """,
                (exam_id, candidate_id, jd_id),
            )
            rows = cursor.fetchall()
            by_question: dict[int, list[tuple[int, str]]] = {}
            for evaluation_id, question_id, status in rows:
                by_question.setdefault(question_id, []).append((evaluation_id, status))
            duplicate_ids = [
                evaluation_id
                for values in by_question.values()
                if sum(status == "Completed" for _, status in values) == 1
                for evaluation_id, status in values
                if status == "Pending"
            ]
            if duplicate_ids:
                cursor.execute(
                    """
                    UPDATE public.answer_evaluation
                    SET evaluation_status = 'Superseded',
                        evaluation_notes = COALESCE(evaluation_notes, '') ||
                            ' Superseded because a completed Stage 1 evaluation exists for this question.'
                    WHERE evaluation_id = ANY(%s)
                    """,
                    (duplicate_ids,),
                )
        conn.commit()
        return len(duplicate_ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def calculate_first_six_average(
    evaluations: Iterable[tuple[int, int, Any, str, Optional[str]]],
) -> Optional[Decimal]:
    """Average six latest scored answers, including answers flagged for review."""

    latest_by_question: dict[int, tuple[int, Any, str, Optional[str]]] = {}
    for evaluation_id, question_id, answer_score, evaluation_status, candidate_answer in evaluations:
        current = latest_by_question.get(question_id)
        if current is None or evaluation_id > current[0]:
            latest_by_question[question_id] = (
                evaluation_id,
                answer_score,
                evaluation_status,
                candidate_answer,
            )

    if len(latest_by_question) != 6:
        return None

    scores = []
    for _, answer_score, evaluation_status, candidate_answer in latest_by_question.values():
        if (
            evaluation_status not in {"Completed", "Review Required"}
            or answer_score is None
            or candidate_answer is None
        ):
            return None
        try:
            score = Decimal(str(answer_score))
        except (InvalidOperation, ValueError):
            return None
        if not score.is_finite() or score < 0 or score > 100:
            return None
        scores.append(score)

    average = sum(scores, Decimal("0")) / Decimal(6)
    return average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_first_six_average(
    candidate_id: int,
    jd_id: int,
    exam_id: str | None = None,
) -> Optional[Decimal]:
    """Calculate one candidate's Stage 1 average without persisting it."""

    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT ae.evaluation_id, ae.question_id, ae.answer_score,
                       ae.evaluation_status, ae.candidate_answer
                FROM public.answer_evaluation ae
                JOIN public.question_exam qe
                  ON qe.exam_id = ae.exam_id
                 AND qe.jd_id = ae.jd_id
                 AND qe.question_id = ae.question_id
                 AND qe.stage = 1
                WHERE ae.candidate_id = %s
                  AND ae.jd_id = %s
                  AND ae.evaluation_status <> 'Superseded'
            """
            params: list[Any] = [candidate_id, jd_id]
            if exam_id is not None:
                query += " AND ae.exam_id = %s"
                params.append(str(exam_id))
            query += " ORDER BY ae.evaluation_id"
            cursor.execute(query, tuple(params))
            evaluations = cursor.fetchall()
        return calculate_first_six_average(evaluations)
    finally:
        conn.close()


def save_candidate_answer(
    jd_id: int,
    question_id: int,
    candidate_answer: Optional[str],
    candidate_id: int,
    exam_id: str | None = None,
    question_source: str | None = None,
) -> int:
    """Insert a pending evaluation record into answer_evaluation."""

    if isinstance(candidate_id, bool) or not isinstance(candidate_id, int) or candidate_id < 1:
        raise ValueError("candidate_id must be a positive integer.")
    detail = get_question_details(jd_id, question_id, exam_id, question_source=question_source)
    source_to_save = question_source or detail.get("question_source", "Question Bank")
    candidate_text = None if candidate_answer is None else str(candidate_answer)

    conn = get_database_connection()
    try:
        ensure_answer_evaluation_table(conn)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT evaluation_id
                FROM public.answer_evaluation
                WHERE candidate_id = %s
                  AND jd_id = %s
                  AND exam_id IS NOT DISTINCT FROM %s
                  AND question_id = %s
                  AND (question_source IS NOT DISTINCT FROM %s OR question_source IS NULL)
                  AND candidate_answer IS NOT DISTINCT FROM %s
                  AND evaluation_status = 'Pending'
                LIMIT 1
                """,
                (candidate_id, jd_id, exam_id, question_id, source_to_save, candidate_text),
            )
            existing = cursor.fetchone()
            if existing:
                raise ValueError(
                    "A pending submission for this jd_id/question_id and candidate answer already exists. "
                    f"evaluation_id={existing[0]}"
                )

            max_marks = get_max_marks_for_difficulty(detail.get("difficulty"))
            expected_facts = detail.get("expected_concepts")
            if expected_facts is not None and not isinstance(expected_facts, (dict, list, str)):
                expected_facts = json.loads(json.dumps(expected_facts))

            cursor.execute(
                """
                INSERT INTO public.answer_evaluation (
                    candidate_id,
                    jd_id,
                    question_id,
                    expected_answer,
                    candidate_answer,
                    difficulty,
                    max_marks,
                    expected_facts,
                    exam_id,
                    evaluation_status,
                    evaluation_notes,
                    evaluated_at,
                    question_source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                RETURNING evaluation_id
                """,
                (
                    candidate_id,
                    jd_id,
                    question_id,
                    detail.get("expected_answer"),
                    candidate_text,
                    detail.get("difficulty"),
                    max_marks,
                    json.dumps(expected_facts) if expected_facts is not None else None,
                    exam_id,
                    "Pending",
                    "Candidate answer recorded and awaiting evaluation.",
                    source_to_save,
                ),
            )
            inserted_id = cursor.fetchone()[0]
        conn.commit()
        return int(inserted_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_exam_session_status(exam_id: str, status: str) -> None:
    """Update exam_sessions status safely."""
    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE public.exam_sessions SET status = %s WHERE exam_id = %s",
                (status, str(exam_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_exam_session_status(exam_id: str) -> str | None:
    """Fetch status from public.exam_sessions."""
    conn = get_database_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM public.exam_sessions WHERE exam_id = %s", (str(exam_id),))
            row = cursor.fetchone()
            return str(row[0]) if row else None
    finally:
        conn.close()


def get_pending_answers() -> List[Dict[str, Any]]:
    """Return all answer_evaluation rows that are still pending."""

    conn = get_database_connection()
    try:
        ensure_answer_evaluation_table(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM public.answer_evaluation
                WHERE evaluation_status = 'Pending'
                ORDER BY evaluation_id
                """
            )
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def get_evaluation_by_id(evaluation_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single evaluation row by evaluation_id."""

    conn = get_database_connection()
    try:
        ensure_answer_evaluation_table(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM public.answer_evaluation
                WHERE evaluation_id = %s
                """,
                (evaluation_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
    finally:
        conn.close()


def update_evaluation_result(evaluation_id: int, result: Dict[str, Any]) -> None:
    """Update the evaluation record with computed metrics."""

    conn = get_database_connection()
    try:
        ensure_answer_evaluation_table(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.answer_evaluation
                SET semantic_score = %s,
                    factual_correctness_score = %s,
                    answer_score = %s,
                    classification = %s,
                    obtained_marks = %s,
                    max_marks = %s,
                    evaluation_status = %s,
                    evaluation_notes = %s,
                    evaluated_at = NOW()
                WHERE evaluation_id = %s
                  AND evaluation_status = 'Pending'
                """,
                (
                    result.get("semantic_score"),
                    result.get("factual_correctness_score"),
                    result.get("answer_score"),
                    result.get("classification"),
                    result.get("obtained_marks"),
                    result.get("max_marks"),
                    result.get("evaluation_status"),
                    result.get("evaluation_notes"),
                    evaluation_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Evaluation {evaluation_id} was not updated because it is no longer pending. "
                    "Existing reviewed results were left unchanged."
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
