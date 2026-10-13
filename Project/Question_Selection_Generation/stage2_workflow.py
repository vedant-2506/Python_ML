"""Database orchestration for one candidate's idempotent adaptive Stage 2 batch."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .adaptive_policy import (
    DEFAULT_STAGE2_DISTRIBUTION,
    calculate_percentage,
    determine_stage2_difficulty,
    resolve_stage2_difficulty,
)
from .config import GROQ_MODEL
from .db_helper import connect
from .llm_question_generator import GeneratedQuestion, generate_stage2_questions
from .question_selector import classify_skills, load_project_vocabulary, question_hash


class Stage2StateError(RuntimeError):
    """Raised when the exam state cannot safely produce or reuse a batch."""


@contextmanager
def _transaction() -> Iterator:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _lock(connection, exam_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"stage2:{exam_id}",))


def _existing_batch(connection, exam_id: str, candidate_id: int, jd_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT ai_question_exam_id, question_order, skill, difficulty,
                      question, reference_answer, expected_concepts, model_name
               FROM public.ai_question_exam
               WHERE exam_id = %s AND candidate_id = %s AND jd_id = %s
               ORDER BY question_order""",
            (str(exam_id), candidate_id, jd_id),
        )
        rows = cursor.fetchall()
    if not rows:
        return []
    if [row[1] for row in rows] != [1, 2, 3, 4]:
        raise Stage2StateError("an incomplete Stage 2 batch exists; refusing to append or overwrite it")
    if any(not row[2] or not row[3] or not row[4] or not row[5] or not row[6] for row in rows):
        raise Stage2StateError("an invalid Stage 2 batch exists; refusing to append or overwrite it")
    difficulties = {difficulty: sum(row[3] == difficulty for row in rows) for difficulty in ("Easy", "Medium", "Hard")}
    if difficulties not in (
        {"Easy": 3, "Medium": 1, "Hard": 0},
        {"Easy": 2, "Medium": 2, "Hard": 0},
        {"Easy": 0, "Medium": 3, "Hard": 1},
    ):
        raise Stage2StateError("an existing Stage 2 batch has an unsupported difficulty distribution")
    return [
        {
            "ai_question_exam_id": row[0],
            "question_order": row[1],
            "skill": row[2],
            "difficulty": row[3],
            "question": row[4],
            "answer": row[5],
            "expected_concepts": row[6],
            "model_name": row[7],
        }
        for row in rows
    ]


def fetch_stage1_evaluations(connection, exam_id: str, candidate_id: int, jd_id: int) -> list[dict[str, Any]]:
    """Read the latest evaluation per Stage 1 question for this exact exam."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT DISTINCT ON (qe.question_order)
                      ae.evaluation_id, ae.question_id, qe.question_order, qe.difficulty,
                      ae.obtained_marks, COALESCE(ae.max_marks,
                          CASE qe.difficulty WHEN 'Easy' THEN 6 WHEN 'Medium' THEN 12 WHEN 'Hard' THEN 18 END),
                      ae.evaluation_status
               FROM public.answer_evaluation ae
               JOIN public.question_exam qe
                 ON qe.exam_id = %s AND qe.jd_id = ae.jd_id
                AND qe.question_id = ae.question_id AND qe.stage = 1
               WHERE ae.candidate_id = %s AND ae.jd_id = %s
                 AND ae.exam_id = %s
                 AND ae.evaluation_status <> 'Superseded'
               ORDER BY qe.question_order, ae.evaluation_id DESC""",
            (str(exam_id), candidate_id, jd_id, str(exam_id)),
        )
        rows = cursor.fetchall()
    return [
        {
            "evaluation_id": row[0],
            "question_id": row[1],
            "question_order": row[2],
            "difficulty": row[3],
            "obtained_marks": row[4],
            "max_marks": row[5],
            "evaluation_status": row[6],
        }
        for row in rows
    ]


def _jd_and_skills(connection, jd_id: int) -> tuple[dict[str, Any], list[str]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT jd_id, job_title, structured_data FROM public.job_description WHERE jd_id = %s", (jd_id,))
        row = cursor.fetchone()
    if row is None:
        raise Stage2StateError(f"job description {jd_id} was not found")
    payload = row[2] or {}
    jd = {"jd_id": row[0], "job_title": row[1] or payload.get("job_title", ""), **payload}
    classification = classify_skills(jd.get("expected_skills", []), load_project_vocabulary(connection))
    return jd, classification.changeable_skills


def _used_questions(connection, exam_id: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT question FROM public.question_exam WHERE exam_id = %s", (str(exam_id),))
        stage1 = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT question FROM public.ai_question_exam WHERE exam_id = %s", (str(exam_id),))
        stage2 = [row[0] for row in cursor.fetchall()]
    return stage1 + stage2


def _insert_batch(connection, exam_id: str, jd_id: int, candidate_id: int, questions: list[GeneratedQuestion]) -> None:
    if len(questions) != 4:
        raise ValueError("Stage 2 must contain exactly four questions")
    with connection.cursor() as cursor:
        for order, item in enumerate(questions, start=1):
            question_hash_value = question_hash(item.question)
            cursor.execute(
                """INSERT INTO public.generated_questions
                   (exam_id, jd_id, skill, question, reference_answer,
                    expected_concepts, difficulty, model_name, question_hash)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                   ON CONFLICT (exam_id, question_hash) DO UPDATE
                   SET model_name = EXCLUDED.model_name
                   RETURNING generated_question_id""",
                (
                    str(exam_id), jd_id, item.skill, item.question, item.reference_answer,
                    json.dumps(item.expected_concepts), item.difficulty, GROQ_MODEL, question_hash_value,
                ),
            )
            generated_question_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO public.ai_question_exam
                   (exam_id, jd_id, candidate_id, question_order, source, question,
                    answer, reference_answer, expected_concepts, difficulty, skill,
                    question_hash, model_name)
                   VALUES (%s, %s, %s, %s, 'groq_llm', %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                   ON CONFLICT (exam_id, candidate_id, question_order) DO NOTHING""",
                (
                    str(exam_id), jd_id, candidate_id, order, item.question, item.reference_answer,
                    item.reference_answer, json.dumps(item.expected_concepts), item.difficulty, item.skill,
                    question_hash_value, GROQ_MODEL,
                ),
            )
            cursor.execute(
                """INSERT INTO public.question_exam
                   (exam_id, jd_id, question_order, stage, source, generated_question_id,
                    question, reference_answer, expected_concepts, difficulty, skill)
                   VALUES (%s, %s, %s, 2, 'LLM', %s, %s, %s, %s::jsonb, %s, %s)
                   ON CONFLICT (exam_id, question_order) DO NOTHING""",
                (
                    str(exam_id), jd_id, order + 6, generated_question_id, item.question,
                    item.reference_answer, json.dumps(item.expected_concepts), item.difficulty, item.skill,
                ),
            )


def generate_or_reuse_stage2(
    exam_id: str | uuid.UUID, jd_id: int, candidate_id: int
) -> dict[str, Any]:
    """Generate once, atomically persist, and return the Stage 2 summary."""
    exam_id = str(exam_id)
    with _transaction() as connection:
        _lock(connection, exam_id)
        existing = _existing_batch(connection, exam_id, candidate_id, jd_id)
        if existing:
            return {"reused": True, "questions": existing}

        evaluations = fetch_stage1_evaluations(connection, exam_id, candidate_id, jd_id)
        distribution, percentage, is_adaptive = resolve_stage2_difficulty(evaluations)
        jd, changeable_skills = _jd_and_skills(connection, jd_id)
        if not changeable_skills:
            raise Stage2StateError("JD has no usable Changeable Skills; no unrelated fallback is permitted")
        used = _used_questions(connection, exam_id)

    questions = generate_stage2_questions(
        jd,
        changeable_skills,
        float(percentage) if percentage is not None else None,
        used,
        difficulty_distribution=distribution,
    )

    with _transaction() as connection:
        _lock(connection, exam_id)
        existing = _existing_batch(connection, exam_id, candidate_id, jd_id)
        if existing:
            return {
                "reused": True,
                "percentage": percentage,
                "adaptive": is_adaptive,
                "distribution": distribution,
                "questions": existing,
                "model": GROQ_MODEL,
            }
        _insert_batch(connection, exam_id, jd_id, candidate_id, questions)
        saved = _existing_batch(connection, exam_id, candidate_id, jd_id)
        if len(saved) != 4:
            raise Stage2StateError("Stage 2 persistence verification failed")
        return {
            "reused": False,
            "percentage": percentage,
            "adaptive": is_adaptive,
            "distribution": distribution,
            "questions": saved,
            "model": GROQ_MODEL,
        }
