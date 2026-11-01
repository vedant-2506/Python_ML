from fastapi import APIRouter, Depends
from ..core.database import connection
from ..core.security import current_company
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM job_description
                       WHERE comp_id=%s AND (status IS NULL OR status NOT IN ('Inactive','Closed','Archived'))""",
                    (user["comp_id"],))
        jobs = cur.fetchone()[0]
        cur.execute("""SELECT count(DISTINCT jc.candidate_id) FROM job_candidate jc
                       JOIN job_description j ON j.jd_id=jc.jd_id
                       WHERE j.comp_id=%s AND (j.status IS NULL OR j.status NOT IN ('Inactive','Closed','Archived'))""", (user["comp_id"],))
        candidates = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM job_shortlist s JOIN job_description j ON j.jd_id=s.jd_id
                       WHERE j.comp_id=%s AND s.status='SELECTED'""", (user["comp_id"],))
        sent = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM final_evaluation_result r JOIN job_description j ON j.jd_id=r.jd_id
                       WHERE j.comp_id=%s""", (user["comp_id"],))
        hired = cur.fetchone()[0]
        cur.execute("""SELECT j.jd_id,j.job_title,j.status,j.department,j.created_at,COUNT(jc.candidate_id)
                       FROM job_description j LEFT JOIN job_candidate jc ON jc.jd_id=j.jd_id
                       WHERE j.comp_id=%s AND (j.status IS NULL OR j.status NOT IN ('Inactive','Closed','Archived'))
                       GROUP BY j.jd_id ORDER BY j.created_at DESC LIMIT 10""", (user["comp_id"],))
        recent = cur.fetchall()
    return {
        "total_jobs": jobs,
        "jobs": jobs,
        "candidates": candidates,
        "shortlisted": sent,
        "hired": hired,
        "recent_jobs": [
            {"jd_id": r[0], "title": r[1], "status": r[2] or "Active",
             "department": r[3], "created_at": r[4], "candidate_count": r[5]}
            for r in recent
        ],
    }
