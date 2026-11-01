from datetime import datetime, timedelta, timezone
from psycopg2.extras import Json
from Question_Selection_Generation.exam_workflow import create_exam
from Question_Selection_Generation.stage2_workflow import generate_or_reuse_stage2
from ..core.database import transaction
from ..core.security import exam_token_hash, new_exam_token
from ..core.config import get_settings


def create_invitation(conn, jd_id: int, candidate_id: int) -> tuple[str, str]:
    exam_id, _ = create_exam(conn, jd_id)
    token, token_hash = new_exam_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=get_settings().exam_link_expiry_hours)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO exam_invitation(exam_id,jd_id,candidate_id,token_hash,expires_at)
                       VALUES(%s,%s,%s,%s,%s) RETURNING invitation_id""",
                    (str(exam_id), jd_id, candidate_id, token_hash, expires))
    return str(exam_id), token


def resolve_token(token: str, for_update: bool = False) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            suffix = " FOR UPDATE" if for_update else ""
            cur.execute("""SELECT i.invitation_id,i.exam_id,i.jd_id,i.candidate_id,i.expires_at,i.status,
                                  e.status,e.started_at,e.ends_at
                           FROM exam_invitation i JOIN exam_sessions e ON e.exam_id=i.exam_id
                           WHERE i.token_hash=%s""" + suffix, (exam_token_hash(token),))
            row = cur.fetchone()
            if not row:
                raise LookupError("Exam link is invalid")
            expires_at = _as_aware(row[4])
            if expires_at <= datetime.now(timezone.utc) and row[5] not in ("COMPLETED", "EXPIRED"):
                cur.execute("UPDATE exam_invitation SET status='EXPIRED' WHERE invitation_id=%s", (row[0],))
                raise TimeoutError("Exam link has expired")
            if row[5] == "COMPLETED" or row[6] == "COMPLETED":
                raise PermissionError("This exam has already been submitted")
            return {"invitation_id": row[0], "exam_id": str(row[1]), "jd_id": row[2],
                    "candidate_id": row[3], "expires_at": expires_at, "invitation_status": row[5],
                    "exam_status": row[6], "started_at": _as_aware(row[7]),
                    "ends_at": _as_aware(row[8])}


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def public_questions(conn, exam_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT question_order,stage,difficulty,max_marks,skill,question
                       FROM question_exam WHERE exam_id=%s ORDER BY question_order""", (exam_id,))
        rows = cur.fetchall()
        return [{"order": r[0], "stage": r[1], "difficulty": r[2], "max_marks": float(r[3] or 0),
                 "skill": r[4], "question": r[5]} for r in rows]


def generate_stage2(exam_id: str, jd_id: int, candidate_id: int) -> dict:
    return generate_or_reuse_stage2(exam_id, jd_id, candidate_id)
