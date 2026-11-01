from fastapi import APIRouter, Depends
from ..core.database import connection
from ..core.security import current_company
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM job_description WHERE comp_id=%s", (user["comp_id"],))
        jobs = cur.fetchone()[0]
        cur.execute("""SELECT count(DISTINCT jc.candidate_id) FROM job_candidate jc
                       JOIN job_description j ON j.jd_id=jc.jd_id WHERE j.comp_id=%s""", (user["comp_id"],))
        candidates = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM exam_invitation i JOIN job_description j ON j.jd_id=i.jd_id
                       WHERE j.comp_id=%s""", (user["comp_id"],))
        sent = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM final_evaluation_result r JOIN job_description j ON j.jd_id=r.jd_id
                       WHERE j.comp_id=%s""", (user["comp_id"],))
        hired = cur.fetchone()[0]
    return {
        "total_jobs": jobs,
        "jobs": jobs,
        "candidates": candidates,
        "shortlisted": sent,
        "hired": hired,
    }
