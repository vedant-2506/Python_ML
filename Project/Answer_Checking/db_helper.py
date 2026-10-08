"""Safe persistence boundary for answer evaluation."""

from __future__ import annotations

import sys
from pathlib import Path
from contextlib import contextmanager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Question_Generation.database import connect

SCHEMA_FILE = Path(__file__).with_name("answer_store_schema.sql")


@contextmanager
def transaction():
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_answer_store(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    connection.commit()


def fetch_exam_question(connection, exam_question_id: int) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("""SELECT exam_question_id, jd_id, question, reference_answer,
                          expected_concepts, difficulty, source
                          FROM question_exam WHERE exam_question_id = %s""", (exam_question_id,))
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Exam question {exam_question_id} was not found")
    return dict(zip(("exam_question_id", "jd_id", "question", "reference_answer", "expected_concepts", "difficulty", "source"), row))


def store_evaluation(connection, candidate_id: int, question: dict, answer: str, result) -> int:
    if not str(answer or "").strip():
        raise ValueError("candidate answer cannot be empty for storage")
    with connection.cursor() as cursor:
        cursor.execute("""INSERT INTO answer_store
            (candidate_id, jd_id, exam_question_id, can_answer, can_answer_vector,
             semantic_score, concept_score, completeness_score, marks)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (candidate_id, exam_question_id) DO UPDATE SET
              can_answer=EXCLUDED.can_answer, can_answer_vector=EXCLUDED.can_answer_vector,
              semantic_score=EXCLUDED.semantic_score, concept_score=EXCLUDED.concept_score,
              completeness_score=EXCLUDED.completeness_score, marks=EXCLUDED.marks,
              submitted_at=CURRENT_TIMESTAMP
            RETURNING answer_id""",
            (candidate_id, question["jd_id"], question["exam_question_id"], answer,
             result.candidate_vector, result.semantic_score, result.concept_score,
             result.completeness_score, result.final_score))
        return cursor.fetchone()[0]


def update_candidate_score(connection, candidate_id: int, final_score: float) -> None:
    if not 0 <= float(final_score) <= 100:
        raise ValueError("final exam score must be between 0 and 100")
    with connection.cursor() as cursor:
        cursor.execute("UPDATE candidate SET final_score = %s WHERE candidate_id = %s", (final_score, candidate_id))
        if cursor.rowcount != 1:
            raise ValueError(f"Candidate {candidate_id} was not found")