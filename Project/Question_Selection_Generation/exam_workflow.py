"""Small persistence boundary for the two-stage exam question workflow."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

try:
    from .question_selector import SelectedQuestion, classify_skills, load_project_vocabulary, select_stage1_questions, validate_stage1_questions
except ImportError:
    from question_selector import SelectedQuestion, classify_skills, load_project_vocabulary, select_stage1_questions, validate_stage1_questions


def create_exam(connection, jd_id: int, rng=None) -> tuple[uuid.UUID, dict]:
    jd = _fetch_jd(connection, jd_id)
    exam_id = uuid.uuid4()
    started_at = datetime.utcnow()
    ends_at = started_at + timedelta(minutes=30)
    with connection.cursor() as cursor:
        cursor.execute("""INSERT INTO exam_sessions (exam_id, jd_id, started_at, ends_at, duration_minutes, status)
                         VALUES (%s,%s,%s,%s,30,'STAGE1_READY')""", (str(exam_id), jd_id, started_at, ends_at))
    return exam_id, {"jd": jd, "started_at": started_at, "ends_at": ends_at}


def _fetch_jd(connection, jd_id: int) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT jd_id, job_title, structured_data FROM job_description WHERE jd_id = %s", (jd_id,))
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Job description {jd_id} was not found")
    payload = row[2] or {}
    return {"jd_id": row[0], "job_title": row[1] or payload.get("job_title", ""), **payload}


def select_and_store_stage1(connection, exam_id, jd_id: int, rng=None) -> tuple[list[SelectedQuestion], list[str], list[str]]:
    existing = existing_exam_questions(connection, exam_id, stage=1)
    if existing:
        return existing, [], []
    jd = _fetch_jd(connection, jd_id)
    core, changing = classify_skills(jd.get("expected_skills", []), load_project_vocabulary(connection))
    selected = select_stage1_questions(connection, core, rng=rng)
    errors = validate_stage1_questions(selected)
    if errors:
        raise ValueError("Stage 1 validation failed: " + "; ".join(errors))
    with connection.cursor() as cursor:
        for order, item in enumerate(selected, start=1):
            cursor.execute("""INSERT INTO question_exam
                (exam_id, jd_id, question_order, stage, source, question_id, question, reference_answer, expected_concepts, difficulty)
                VALUES (%s,%s,%s,1,'Question Bank',%s,%s,%s,%s::jsonb,%s)""",
                (str(exam_id), jd_id, order, item.question_id, item.question, item.answer,
                 json.dumps([concept.strip() for concept in item.expected_concepts.split(',') if concept.strip()]), item.difficulty))
        cursor.execute("UPDATE exam_sessions SET status='STAGE1_SUBMITTED' WHERE exam_id=%s", (str(exam_id),))
    return selected, core, changing


def existing_exam_questions(connection, exam_id, stage: int | None = None) -> list:
    query = """SELECT question_id, question, reference_answer, expected_concepts, difficulty, skill
               FROM question_exam WHERE exam_id = %s"""
    parameters: list = [str(exam_id)]
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
    from question_selector import average_score, determine_stage2_difficulty
    average = average_score(scores)
    return {"average": average, "difficulty_distribution": determine_stage2_difficulty(average), "skill_performance": skill_scores or {}}
