import os
from fastapi import APIRouter, Depends, HTTPException
from ..core.config import get_settings
from ..core.database import connection, transaction
from ..core.security import current_company
from ..schemas.common import SendExamRequest
from ..services.exam_service import create_invitation
from ..services.mail_service import send_email, exam_invite_html
from ..services.ats_service import ranked_candidates

router = APIRouter(prefix="/api/jobs", tags=["exams"])


@router.post("/{jd_id}/send-exam")
def send_exam(jd_id: int, payload: SendExamRequest, user=Depends(current_company)):
    """Create exam invitations for the top N candidates and return direct exam links.
    Email is optional (SEND_EXAM_EMAILS=true in Backend/.env); links are always returned."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT job_title FROM job_description WHERE jd_id=%s AND comp_id=%s", (jd_id, user["comp_id"]))
        job = cur.fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        cur.execute("SELECT company_name FROM company WHERE comp_id=%s", (user["comp_id"],))
        company = cur.fetchone()[0]
        selected = payload.candidate_ids or [
            r["candidate_id"] for r in ranked_candidates(conn, jd_id)[: payload.top_n or 5]
        ]
        cur.execute(
            """SELECT c.candidate_id, c.email, c.candidate_name FROM candidate c
               JOIN job_candidate jc ON jc.candidate_id = c.candidate_id
               WHERE jc.jd_id=%s AND c.candidate_id = ANY(%s)""",
            (jd_id, selected),
        )
        candidates = cur.fetchall()

    order = {cid: i + 1 for i, cid in enumerate(selected)}
    base = get_settings().frontend_base_url
    send_mail = os.getenv("SEND_EXAM_EMAILS", "false").lower() == "true"
    sent, skipped = [], []

    for candidate_id, email, name in sorted(candidates, key=lambda r: order.get(r[0], 999)):
        try:
            with transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM exam_invitation WHERE jd_id=%s AND candidate_id=%s AND status <> 'EXPIRED'",
                        (jd_id, candidate_id),
                    )
                    existing = cur.fetchone()
                    if existing and existing[0] == "COMPLETED":
                        skipped.append({"candidate_id": candidate_id, "reason": "Exam already completed"})
                        continue
                    if existing:  # demo mode: replace the old link with a fresh one
                        cur.execute(
                            "UPDATE exam_invitation SET status='EXPIRED', expires_at=NOW() "
                            "WHERE jd_id=%s AND candidate_id=%s AND status <> 'EXPIRED'",
                            (jd_id, candidate_id),
                        )
                exam_id, token = create_invitation(conn, jd_id, candidate_id)
            link = f"{base}/html/exam-start.html?token={token}"
        except Exception as exc:
            skipped.append({"candidate_id": candidate_id, "reason": f"Could not create exam: {exc}"})
            continue

        email_status = "not sent (link only)"
        if send_mail and email:
            try:
                send_email(email, f"RankResume assessment: {job[0]}", exam_invite_html(company, job[0], link))
                with transaction() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE exam_invitation SET email_sent_at=NOW() WHERE exam_id=%s", (exam_id,))
                email_status = "sent"
            except Exception as exc:
                with transaction() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE exam_invitation SET send_error=%s WHERE exam_id=%s", (str(exc)[:500], exam_id))
                email_status = "failed"
        sent.append({"rank": order.get(candidate_id), "candidate_id": candidate_id, "name": name,
                     "email": email, "exam_link": link, "email_status": email_status})
    return {"sent": sent, "skipped": skipped}


@router.get("/{jd_id}/exam-status")
def exam_status(jd_id: int, user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT i.candidate_id,c.candidate_name,c.email,i.status,i.email_sent_at
               FROM exam_invitation i JOIN candidate c ON c.candidate_id=i.candidate_id
               JOIN job_description j ON j.jd_id=i.jd_id
               WHERE i.jd_id=%s AND j.comp_id=%s AND i.status <> 'EXPIRED' ORDER BY c.candidate_name""",
            (jd_id, user["comp_id"]),
        )
        rows = cur.fetchall()
    return {"items": [dict(zip(["candidate_id", "candidate_name", "email", "status", "email_sent_at"], r)) for r in rows]}
