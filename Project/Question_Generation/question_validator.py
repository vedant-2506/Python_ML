"""Complete audit for the bankresume table and SQL export."""
from __future__ import annotations

import json
import re
import subprocess
import os
from collections import Counter
from pathlib import Path

from database import transaction
from question_deduplicator import duplicate_counts, similarity, normalize
from question_generator import REPORT, SCHEMA, TARGETS

EXPORT = SCHEMA.parent / "question_bank.sql"

SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
REQUIRED = ("question_id", "subject", "topic", "question", "answer", "expected_concepts", "difficulty")


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCES.split(text.strip()) if part.strip()])


def _near_count(values: list[str], threshold: float = 0.86) -> int:
    seen: dict[str, list[str]] = {}
    count = 0
    for value in values:
        key = normalize(value).split()[:3]
        bucket = " ".join(key)
        if any(similarity(value, previous) >= threshold for previous in seen.get(bucket, [])):
            count += 1
        seen.setdefault(bucket, []).append(value)
    return count


def audit() -> dict:
    with transaction() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM question_bank")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT subject, COUNT(*) FROM question_bank GROUP BY subject ORDER BY subject")
            subjects = dict(cursor.fetchall())
            cursor.execute("SELECT topic, COUNT(*) FROM question_bank GROUP BY topic ORDER BY topic")
            topics = dict(cursor.fetchall())
            cursor.execute("SELECT difficulty, COUNT(*) FROM question_bank GROUP BY difficulty ORDER BY difficulty")
            difficulties = dict(cursor.fetchall())
            cursor.execute("""SELECT question_id, subject, topic, question, answer, expected_concepts, difficulty
                            FROM question_bank ORDER BY question_id""")
            rows = cursor.fetchall()
            cursor.execute("""SELECT COUNT(*) FROM question_bank
                WHERE question_id IS NULL OR subject IS NULL OR topic IS NULL OR question IS NULL
                OR answer IS NULL OR expected_concepts IS NULL OR difficulty IS NULL
                OR BTRIM(subject) = '' OR BTRIM(topic) = '' OR BTRIM(question) = ''
                OR BTRIM(answer) = '' OR BTRIM(expected_concepts) = ''""")
            empty = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM question_bank WHERE difficulty NOT IN ('Easy','Medium','Hard')")
            invalid_difficulty = cursor.fetchone()[0]
            cursor.execute("""SELECT LOWER(REGEXP_REPLACE(BTRIM(question), '\\s+', ' ', 'g')), COUNT(*)
                FROM question_bank GROUP BY 1 HAVING COUNT(*) > 1""")
            exact_db = sum(count - 1 for _, count in cursor.fetchall())
            cursor.execute("SELECT COUNT(*) FROM (SELECT question_hash FROM question_bank GROUP BY question_hash HAVING COUNT(*) > 1) d")
            hash_collisions = cursor.fetchone()[0]

    questions = [row[3] for row in rows]
    answers = [row[4] for row in rows]
    exact_q, near_q = duplicate_counts(questions)
    # A high Jaccard threshold catches copied answers while allowing shared
    # terminology that is unavoidable for related core-CS concepts.
    exact_a, near_a = duplicate_counts(answers, near_threshold=0.98)
    sentence_counts = Counter(sentence_count(answer) for answer in answers)
    invalid_sentences = sum(count for number, count in sentence_counts.items() if number not in (5, 6))
    missing_concepts = sum(not row[5].strip() for row in rows)
    inconsistent = 0
    for _, subject, topic, question, answer, concepts, _ in rows:
        concept_words = set(re.findall(r"[a-z0-9]+", topic.lower()))
        answer_words = set(re.findall(r"[a-z0-9]+", answer.lower()))
        if not concept_words.intersection(answer_words) or topic.lower() not in concepts.lower():
            inconsistent += 1

    result = {
        "total": total,
        "subjects": subjects,
        "topics": topics,
        "difficulties": difficulties,
        "empty_records": empty,
        "invalid_difficulty": invalid_difficulty,
        "duplicate_question_count": max(exact_q, exact_db),
        "near_duplicate_question_count": near_q,
        "duplicate_answer_count": exact_a,
        "near_duplicate_answer_count": near_a,
        "hash_collisions": hash_collisions,
        "sentence_counts": {str(key): value for key, value in sorted(sentence_counts.items())},
        "invalid_sentence_count": invalid_sentences,
        "missing_expected_concepts": missing_concepts,
        "inconsistent_records": inconsistent,
        "question_id_unique": len({row[0] for row in rows}) == total,
        "target_met": all(subjects.get(subject, 0) >= target for subject, target in TARGETS.items()),
    }
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def export_sql() -> None:
    output = SCHEMA.read_text(encoding="utf-8")
    with transaction() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT subject, topic, question, answer, expected_concepts, difficulty, question_hash FROM question_bank ORDER BY question_id")
            rows = cursor.fetchall()
    import io
    from psycopg2 import sql
    # Use PostgreSQL's own COPY encoder, then embed a safe COPY payload in the export.
    with transaction() as conn:
        buffer = io.StringIO()
        with conn.cursor() as cursor:
            cursor.copy_expert("COPY (SELECT subject, topic, question, answer, expected_concepts, difficulty, question_hash FROM question_bank ORDER BY question_id) TO STDOUT", buffer)
    output += "\nTRUNCATE public.question_bank RESTART IDENTITY;\n"
    output += "COPY public.question_bank (subject, topic, question, answer, expected_concepts, difficulty, question_hash) FROM stdin;\n"
    output += buffer.getvalue() + "\\.\n"
    EXPORT.write_text(output, encoding="utf-8")


def main() -> int:
    result = audit()
    print(json.dumps(result, indent=2))
    print("SQL export: writing question_bank.sql")
    export_sql()
    passed = (
        result["total"] >= 5000 and result["target_met"] and result["empty_records"] == 0
        and result["invalid_difficulty"] == 0 and result["duplicate_question_count"] == 0
        and result["near_duplicate_question_count"] == 0 and result["duplicate_answer_count"] == 0
        and result["near_duplicate_answer_count"] == 0 and result["invalid_sentence_count"] == 0
        and result["missing_expected_concepts"] == 0 and result["inconsistent_records"] == 0
        and result["question_id_unique"]
    )
    print(f"FINAL STATUS: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
