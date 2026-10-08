"""Database helpers that reuse the existing Question_Generation connection contract."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Question_Generation.database import connect

SCHEMA_FILE = Path(__file__).with_name("selection_generation_schema.sql")


@contextmanager
def transaction() -> Iterator:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_schema(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    connection.commit()


def fetch_jd(connection, jd_id: int) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT jd_id, job_title, structured_data FROM job_description WHERE jd_id = %s",
            (jd_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Job description {jd_id} was not found")
    payload = row[2] or {}
    return {"jd_id": row[0], "job_title": row[1] or payload.get("job_title", ""), "structured_data": payload}


def count_question_bank(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM bankresume")
        return cursor.fetchone()[0]
