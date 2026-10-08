"""PostgreSQL access for the isolated RankResume question bank."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection


def connect() -> connection:
    return psycopg2.connect(
        host=os.getenv("RANKRESUME_DB_HOST", "localhost"),
        port=int(os.getenv("RANKRESUME_DB_PORT", "5432")),
        dbname=os.getenv("RANKRESUME_DB_NAME", "rankresume"),
        user=os.getenv("RANKRESUME_DB_USER", "root"),
        password=os.getenv("RANKRESUME_DB_PASSWORD", "root"),
    )


@contextmanager
def transaction() -> Iterator[connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(conn: connection, schema_file: str) -> None:
    with open(schema_file, encoding="utf-8") as handle:
        with conn.cursor() as cursor:
            cursor.execute(handle.read())
    conn.commit()
