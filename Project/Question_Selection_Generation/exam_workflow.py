"""Transactional, idempotent persistence for the first exam stage."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .question_selector import (
    SelectedQuestion,
    SkillClassification,
    classify_skills,
    load_project_vocabulary,
    select_stage1_questions,
    validate_stage1_questions,
)


@dataclass(frozen=True)
class Stage1Selection:
    exam_id: uuid.UUID
    jd_id: int
    questions: list[SelectedQuestion]
    classification: SkillClassification
    reused: bool


def _fetch_jd(connection, jd_id: int) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT jd_id, job_title, structured_data FROM job_description WHERE jd_id = %s",
            (jd_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Job description {jd_id} was not found")
    payload = row[2] or {}
    return {"jd_id": row[0], "job_title": row[1] or payload.get("job_title", ""), **payload}


def _lock_jd(connection, jd_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"stage1:{jd_id}",))


def _get_or_create_exam(connection, jd_id: int) -> uuid.UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT exam_id FROM exam_sessions
               WHERE jd_id = %s
               ORDER BY started_at DESC, exam_id DESC
               LIMIT 1
               FOR UPDATE""",
            (jd_id,),
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        started_at = datetime.utcnow()
        cursor.execute(
            """INSERT INTO exam_sessions
                 (exam_id, jd_id, started_at, ends_at, duration_minutes, status)
               VALUES (%s, %s, %s, %s, 30, 'STAGE1_READY')
               RETURNING exam_id""",
            (str(uuid.uuid4()), jd_id, started_at, started_at + timedelta(minutes=30)),
        )
        return cursor.fetchone()[0]


def _stage1_rows(connection, exam_id: uuid.UUID) -> list[SelectedQuestion]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT q.question_id, COALESCE(b.subject, q.skill, ''),
                      COALESCE(b.topic, ''), q.question, q.reference_answer,
                      q.expected_concepts, q.difficulty
               FROM question_exam q
               LEFT JOIN bankresume b ON b.question_id = q.question_id
               WHERE q.exam_id = %s AND q.stage = 1
               ORDER BY q.question_order""",
            (str(exam_id),),
        )
        rows = cursor.fetchall()
    result: list[SelectedQuestion] = []
    for row in rows:
        concepts = row[5]
        if isinstance(concepts, list):
            concepts = ", ".join(str(item) for item in concepts)
        result.append(SelectedQuestion(row[0], row[1], row[2], row[3], row[4], str(concepts or ""), row[6]))
    return result


def _session_status(connection, exam_id: uuid.UUID) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT status FROM exam_sessions WHERE exam_id = %s", (str(exam_id),))
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Exam session {exam_id} was not found")
    return row[0]


def _has_submitted_answers(connection, exam_id: uuid.UUID) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS (
                 SELECT 1 FROM answer_store a
                 JOIN question_exam q ON q.exam_question_id = a.exam_question_id
                 WHERE q.exam_id = %s AND q.stage = 1
               )""",
            (str(exam_id),),
        )
        return bool(cursor.fetchone()[0])


def _delete_stage1_rows_for_refresh(connection, exam_id: uuid.UUID) -> None:
    status = _session_status(connection, exam_id)
    if status != "STAGE1_READY" or _has_submitted_answers(connection, exam_id):
        raise RuntimeError(
            f"Stage 1 for exam {exam_id} cannot be refreshed after submission or candidate answers"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM question_exam WHERE exam_id = %s AND stage = 1",
            (str(exam_id),),
        )


def _insert_stage1_rows(connection, exam_id: uuid.UUID, jd_id: int, questions: list[SelectedQuestion]) -> None:
    errors = validate_stage1_questions(questions)
    if errors:
        raise ValueError("Stage 1 validation failed: " + "; ".join(errors))
    with connection.cursor() as cursor:
        for order, item in enumerate(questions, start=1):
            concepts = json.dumps([part.strip() for part in item.expected_concepts.split(",") if part.strip()])
            cursor.execute(
                """INSERT INTO question_exam
                    (exam_id, jd_id, question_order, stage, source, question_id,
                     question, reference_answer, expected_concepts, difficulty, skill)
                   VALUES (%s, %s, %s, 1, 'Question Bank', %s, %s, %s,
                           %s::jsonb, %s, %s)""",
                (
                    str(exam_id),
                    jd_id,
                    order,
                    item.question_id,
                    item.question,
                    item.answer,
                    concepts,
                    item.difficulty,
                    item.subject,
                ),
            )
        cursor.execute(
            "UPDATE exam_sessions SET status = 'STAGE1_SUBMITTED' WHERE exam_id = %s",
            (str(exam_id),),
        )


def select_questions(connection, jd_id: int, refresh: bool = False, rng=None) -> Stage1Selection:
    """Reuse or transactionally create exactly one valid Stage 1 set for a JD."""
    _lock_jd(connection, jd_id)
    jd = _fetch_jd(connection, jd_id)
    classification = classify_skills(jd.get("expected_skills", []), load_project_vocabulary(connection))
    exam_id = _get_or_create_exam(connection, jd_id)
    existing = _stage1_rows(connection, exam_id)
    existing_errors = validate_stage1_questions(existing)
    if existing and not existing_errors and not refresh:
        return Stage1Selection(exam_id, jd_id, existing, classification, True)
    if refresh or existing:
        _delete_stage1_rows_for_refresh(connection, exam_id)
    questions = select_stage1_questions(connection, classification.core_skills, rng=rng)
    _insert_stage1_rows(connection, exam_id, jd_id, questions)
    return Stage1Selection(exam_id, jd_id, questions, classification, False)


def create_exam(connection, jd_id: int, rng=None) -> tuple[uuid.UUID, dict[str, Any]]:
    """Compatibility wrapper; normal callers now reuse a JD's latest session."""
    _lock_jd(connection, jd_id)
    exam_id = _get_or_create_exam(connection, jd_id)
    jd = _fetch_jd(connection, jd_id)
    return exam_id, {"jd": jd}


def select_and_store_stage1(connection, exam_id, jd_id: int, rng=None):
    """Compatibility wrapper for older callers that already selected a session."""
    existing = _stage1_rows(connection, exam_id)
    if existing and not validate_stage1_questions(existing):
        return existing, [], []
    jd = _fetch_jd(connection, jd_id)
    classification = classify_skills(jd.get("expected_skills", []), load_project_vocabulary(connection))
    questions = select_stage1_questions(connection, classification.core_skills, rng=rng)
    _insert_stage1_rows(connection, exam_id, jd_id, questions)
    return questions, classification.core_skills, classification.changeable_skills


def existing_exam_questions(connection, exam_id, stage: int | None = None) -> list:
    query = "SELECT question_id, question, reference_answer, expected_concepts, difficulty, skill FROM question_exam WHERE exam_id = %s"
    parameters: list[Any] = [str(exam_id)]
    if stage is not None:
        query += " AND stage = %s"
        parameters.append(stage)
    query += " ORDER BY question_order"
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        return cursor.fetchall()


def used_questions(connection, exam_id) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT question FROM question_exam WHERE exam_id = %s ORDER BY question_order", (str(exam_id),))
        return [row[0] for row in cursor.fetchall()]


def submit_stage1_scores(scores: list[float], skill_scores: dict[str, float] | None = None) -> dict:
    from .question_selector import average_score, determine_stage2_difficulty

    average = average_score(scores)
    return {"average": average, "difficulty_distribution": determine_stage2_difficulty(average), "skill_performance": skill_scores or {}}
