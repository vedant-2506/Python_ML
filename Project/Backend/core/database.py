from contextlib import contextmanager
from psycopg2.pool import ThreadedConnectionPool
from .config import get_settings

_pool: ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ThreadedConnectionPool(1, 10, host=s.db_host, port=s.db_port,
                                       dbname=s.db_name, user=s.db_user, password=s.db_password)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def connection():
    init_pool()
    assert _pool is not None
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


@contextmanager
def transaction():
    with connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
